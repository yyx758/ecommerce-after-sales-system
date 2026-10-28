from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
from threading import Event
from typing import Any, Literal, Optional, Protocol, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, interrupt

from .contracts import ReviewAssessment, ReviewProposal, TrustedCaseContext
from .evaluators import policy_facts, visual_facts, review_assessment as build_review_assessment
from .synthesis import ComplexReviewSynthesizer
from .confidence import apply_deterministic_confidence
from .sop import (
    ESCALATED_REVIEW_MODE,
    SOP_REVIEW_MODE,
    FormalReviewSop,
)
from ....tools import AgentToolRegistry, ToolResult
from ...skill_registry import AgentSkill, AgentSkillRegistry
from ....application.rag_query_rewrite import RagQueryRewriteService, RagRewriteError
from ....infrastructure.agent_metrics import AGENT_RUNTIME_METRICS
from ....application.rag_retrieval_policy import RagRetrievalPolicy
from ....infrastructure.request_tracing import TraceRecorder, bind_trace_id, current_trace_id
from ....providers.llm_client import get_llm_client


class ReviewTools(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...


class ReviewLlm(Protocol):
    def generate_structured(self, *, system_prompt: str, user_prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        ...


class FormalReviewState(TypedDict, total=False):
    payload: dict[str, Any]
    trace_id: str
    trusted_context: TrustedCaseContext
    ticket_data: dict[str, Any]
    issue: str
    policy_query: str
    policy_facts: dict[str, Any]
    visual_facts: dict[str, Any]
    review_assessment: ReviewAssessment
    review_proposal: ReviewProposal
    gate_action: str
    gate_reasons: list[str]
    evidence_needed: list[str]
    tool_trace: list[dict[str, Any]]
    review_result: Optional[dict[str, Any]]
    evidence_request_applied: bool
    evidence_request_outcome: str
    final_reply: str
    need_human: bool
    failure_reason: Optional[str]
    resume_signal: dict[str, Any]
    review_mode: str
    escalation_reasons: list[str]
    skill_versions: dict[str, str]


_ACTIVE_REVIEW_TRACE: ContextVar[TraceRecorder | None] = ContextVar(
    "active_formal_review_trace",
    default=None,
)
_REVIEW_CANCEL_EVENT: ContextVar[Event | None] = ContextVar(
    "formal_review_cancel_event", default=None
)


@contextmanager
def bind_review_cancellation(event: Event):
    token = _REVIEW_CANCEL_EVENT.set(event)
    try:
        yield
    finally:
        _REVIEW_CANCEL_EVENT.reset(token)


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_score(name: str, default: float) -> float:
    try:
        return max(0.0, min(float(os.getenv(name, str(default))), 1.0))
    except (TypeError, ValueError):
        return default


@dataclass
class FormalReviewWorkflow:
    tools: ReviewTools = field(default_factory=AgentToolRegistry)
    llm: ReviewLlm = field(default_factory=get_llm_client)
    skills: AgentSkillRegistry = field(default_factory=AgentSkillRegistry)
    checkpointer: BaseCheckpointSaver[Any] | None = None
    auto_approve_enabled: bool = field(
        default_factory=lambda: _env_bool(
            "FORMAL_REVIEW_AUTO_APPROVE_ENABLED",
            True,
        )
    )
    minimum_review_confidence: float = field(
        default_factory=lambda: _env_score(
            "FORMAL_REVIEW_MIN_CONFIDENCE",
            0.75,
        )
    )

    def __post_init__(self) -> None:
        self._formal_review_skill_definition = self._require_skill(
            "formal_review"
        )
        self._rewrite_service = RagQueryRewriteService(self.llm)
        self._retrieval_policy = RagRetrievalPolicy()
        graph = StateGraph(FormalReviewState)
        graph.add_node("load_trusted_context", self.load_trusted_context)
        graph.add_node("validate_review_inputs", self.validate_review_inputs)
        graph.add_node("sop_plan", self.sop_plan)
        graph.add_node("policy_review", self.policy_review)
        graph.add_node("visual_review", self.visual_review)
        graph.add_node("review_synthesis", self.review_synthesis)
        graph.add_node("deterministic_gate", self.deterministic_gate)
        graph.add_node("submit_review", self.submit_review)
        graph.add_node("request_missing_evidence", self.request_missing_evidence)
        graph.add_node("await_evidence", self.await_evidence)
        graph.add_node("prepare_resumed_attempt", self.prepare_resumed_attempt)
        graph.add_node("submit_manual_review", self.submit_manual_review)

        graph.set_entry_point("load_trusted_context")
        graph.add_conditional_edges(
            "load_trusted_context",
            self.route_after_context,
            {
                "validate_review_inputs": "validate_review_inputs",
                "submit_manual_review": "submit_manual_review",
            },
        )
        graph.add_conditional_edges(
            "validate_review_inputs",
            self.route_after_input_validation,
            {
                "sop_plan": "sop_plan",
                "request_missing_evidence": "request_missing_evidence",
            },
        )
        graph.add_edge("sop_plan", "policy_review")
        graph.add_edge("sop_plan", "visual_review")
        graph.add_edge(["policy_review", "visual_review"], "review_synthesis")
        graph.add_edge("review_synthesis", "deterministic_gate")
        graph.add_conditional_edges(
            "deterministic_gate",
            self.route_after_gate,
            {
                "submit_review": "submit_review",
                "submit_manual_review": "submit_manual_review",
            },
        )
        graph.add_conditional_edges(
            "request_missing_evidence",
            self.route_after_evidence_request,
            {
                "await_evidence": "await_evidence",
                "end": END,
                "submit_manual_review": "submit_manual_review",
            },
        )
        graph.add_edge("await_evidence", "prepare_resumed_attempt")
        graph.add_edge("prepare_resumed_attempt", "load_trusted_context")
        graph.add_edge("submit_review", END)
        graph.add_edge("submit_manual_review", END)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        return self.start(payload, trace_recorder)

    def start(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        review_id = str(payload.get("review_request_id") or "").strip()
        if not review_id:
            raise ValueError("review_request_id is required")
        trace = trace_recorder if isinstance(trace_recorder, TraceRecorder) else None
        state: FormalReviewState = {
            "payload": dict(payload),
            "trace_id": trace.trace_id if trace else "",
            "issue": str(payload.get("message") or "").strip(),
            "tool_trace": [],
            "review_result": None,
            "evidence_request_applied": False,
            "evidence_request_outcome": "",
            "evidence_needed": [],
            "need_human": False,
            "failure_reason": None,
            "review_mode": SOP_REVIEW_MODE,
            "escalation_reasons": [],
            "skill_versions": self._formal_skill_versions(),
        }
        final = self._invoke(
            state,
            review_id=review_id,
            trace=trace,
            operation="start",
        )
        return self._format_result(final)

    def resume(
        self,
        review_id: str,
        resume_signal: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        normalized_review_id = str(review_id or "").strip()
        if not normalized_review_id:
            raise ValueError("review_id is required")
        if self.checkpointer is None:
            raise RuntimeError("durable checkpointer is required to resume a review")
        trace = trace_recorder if isinstance(trace_recorder, TraceRecorder) else None
        final = self._invoke(
            Command(resume=dict(resume_signal)),
            review_id=normalized_review_id,
            trace=trace,
            operation="resume",
        )
        return self._format_result(final)

    def _invoke(
        self,
        graph_input: FormalReviewState | Command,
        *,
        review_id: str,
        trace: TraceRecorder | None,
        operation: str,
    ) -> dict[str, Any]:
        self._raise_if_cancelled()
        bind_llm = getattr(self.llm, "bind_trace", None)
        if callable(bind_llm):
            bind_llm(trace)
        trace_token = _ACTIVE_REVIEW_TRACE.set(trace)
        try:
            with bind_trace_id(trace.trace_id if trace else None):
                with self._trace_step(
                    trace,
                    "formal_review_skill",
                    review_request_id=review_id,
                    operation=operation,
                ) as trace_step:
                    final = self.graph.invoke(
                        graph_input,
                        config={"configurable": {"thread_id": review_id}},
                    )
                    trace_step.details.update(
                        {
                            "gate_action": final.get("gate_action"),
                            "need_human": bool(final.get("need_human")),
                            "failure_reason": final.get("failure_reason"),
                        }
                    )
        finally:
            _ACTIVE_REVIEW_TRACE.reset(trace_token)
            if callable(bind_llm):
                bind_llm(None)

        return final

    def _format_result(self, final: dict[str, Any]) -> dict[str, Any]:
        context = final.get("trusted_context")
        ticket = final.get("review_result") or final.get("ticket_data") or {}
        payload = final.get("payload") or {}
        paused = bool(final.get("__interrupt__"))
        return {
            "assistant_reply": final.get("final_reply") or "",
            "session_mode": "AI",
            "tool_trace": final.get("tool_trace") or [],
            "ticket": self._ticket_payload(ticket),
            "review_result": final.get("review_result"),
            "need_human": bool(final.get("need_human")),
            "evidence_needed": list(
                final.get('evidence_needed')
                or (final.get('review_assessment').missing_evidence if final.get('review_assessment') else ())
            ),
            "persistence": {
                "session_id": context.session_id if context else payload.get("session_id"),
                "ticket_no": ticket.get("ticket_no") if isinstance(ticket, dict) else None,
            },
            "raw": {
                "runtime": "formal_review_skill",
                "review_mode": final.get("review_mode") or SOP_REVIEW_MODE,
                "escalation_reasons": final.get("escalation_reasons") or [],
                "skill_versions": final.get("skill_versions")
                or self._formal_skill_versions(),
                "context_version": context.context_version if context else None,
                "evidence_revision": context.evidence_revision if context else None,
                "paused": paused,
                "gate_action": final.get("gate_action"),
                "gate_reasons": final.get("gate_reasons") or [],
                "evidence_request_applied": bool(
                    final.get("evidence_request_applied")
                ),
                "failure_reason": final.get("failure_reason"),
                "review_assessment": self._as_dict(final.get('review_assessment')),
                "review_proposal": self._as_dict(final.get("review_proposal")),
            },
        }

    def load_trusted_context(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        payload = state["payload"]
        arguments = {
            "user_id": str(payload.get("user_id") or ""),
            "ticket_id": str(payload.get("ticket_id") or ""),
            "order_id": payload.get("order_id"),
        }
        with self._node_trace(
            state,
            "review_load_trusted_context",
        ) as trace_step:
            result = self.tools.call("get_after_sales_ticket", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        trace = [self._trace_entry(result, arguments)]
        if not result.ok or not isinstance(result.data, dict):
            return {
                "tool_trace": trace,
                "failure_reason": result.error_category or "ticket_lookup_failed",
                "gate_action": "MANUAL_REVIEW",
                "gate_reasons": ["trusted_context_unavailable"],
                "need_human": True,
            }
        context = TrustedCaseContext.from_ticket(payload, result.data)
        # The ticket stored by Java is the business source of truth. Kafka's
        # message is often only a generic event description and must not dilute
        # the policy retrieval query.
        issue = context.issue_description
        trace_step.details["ticket_status"] = context.ticket_status
        if context.ticket_status not in {"PENDING", "PENDING_REVIEW"}:
            return {
                "tool_trace": trace,
                "ticket_data": dict(result.data),
                "trusted_context": context,
                "failure_reason": "ticket_status_changed",
                "gate_action": "MANUAL_REVIEW",
                "gate_reasons": ["ticket_status_changed"],
                "need_human": True,
            }
        return {
            "tool_trace": trace,
            "ticket_data": dict(result.data),
            "trusted_context": context,
            "issue": issue,
        }

    def validate_review_inputs(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        context = state["trusted_context"]
        ticket = state.get("ticket_data") or {}
        has_issue_description = any(
            str(ticket.get(field) or "").strip()
            for field in ("reason_detail", "description")
        )
        missing: list[str] = []
        if not has_issue_description:
            missing.append("问题描述")
        if not context.attachments:
            missing.append("商品问题图片")
        with self._node_trace(
            state,
            "review_validate_inputs",
        ) as trace_step:
            trace_step.details.update(
                {
                    "has_issue_description": has_issue_description,
                    "has_image_evidence": bool(context.attachments),
                    "missing_input_count": len(missing),
                }
            )
        if missing:
            return {
                "gate_action": "REQUEST_EVIDENCE",
                "gate_reasons": ["evidence_missing"],
                "evidence_needed": missing,
                "need_human": False,
            }
        return {"evidence_needed": []}

    def sop_plan(self, state: FormalReviewState) -> FormalReviewState:
        query = FormalReviewSop.plan(state['trusted_context'], state.get('issue') or '')
        return {'policy_query': query}

    def policy_review(self, state: FormalReviewState) -> FormalReviewState:
        context = state['trusted_context']
        query = state['policy_query']
        arguments = {
            'user_id': context.user_id,
            'query': query,
            'merchant_code': context.merchant_code,
            'product_category': context.product_category,
            'source_type': 'after_sales_policy',
            'policy_version': context.policy_version,
            'as_of_time': context.business_time,
            'top_k': 5,
        }
        with self._node_trace(state, 'review_policy') as trace_step:
            result = self.tools.call('retrieve_knowledge', arguments)
            facts = policy_facts(context, result)
            if (
                result.ok
                and isinstance(result.data, dict)
                and not facts['trusted_policy_eligible']
                and not self._retrieval_policy.is_infrastructure_failure(result.data)
            ):
                try:
                    skill = self._formal_review_skill_definition
                    decision = self._rewrite_service.evaluate(
                        user_question=state.get('issue') or '',
                        task=(
                            '只改写可信售后政策检索问题，不作业务决定。\n'
                            f'Active skill ({skill.name}@{skill.version}):\n'
                            f'{self._formal_skill_instructions("policy-review.md")}'
                        ),
                        known_facts={
                            'product_name': context.product_name,
                            'product_category': context.product_category,
                            'issue_type': state.get('issue') or '',
                            'after_sales_type': context.after_sales_type,
                            'scene': 'formal_review',
                            'intent': 'trusted_policy_retrieval',
                        },
                        original_query=query,
                        previous_queries=[],
                        require_trusted_policy=True,
                        retrieval_result=result.data,
                        allow_rewrite=True,
                    )
                    queries = tuple(
                        item.query for item in decision.queries
                        if str(item.query or '').strip()
                    )[:3] if not decision.sufficient else ()
                    if queries:
                        revised = self.tools.call('retrieve_knowledge_multi', {
                            **arguments,
                            'original_query': query,
                            'queries': list(queries),
                        })
                        facts = policy_facts(context, revised)
                        result = revised
                except RagRewriteError:
                    facts['policy_issues'] = tuple(dict.fromkeys(
                        (*facts['policy_issues'], 'rag_query_rewrite_failed')
                    ))
            trace_step.details.update({
                'success': facts['policy_success'],
                'retrieval_mode': facts['retrieval_mode'],
                'trusted_policy_eligible': facts['trusted_policy_eligible'],
                'citation_count': len(facts['citations']),
            })
        return {'policy_facts': facts}

    def visual_review(self, state: FormalReviewState) -> FormalReviewState:
        context = state['trusted_context']
        skill = self._formal_review_skill_definition
        with self._node_trace(state, 'review_visual') as trace_step:
            result = self.tools.call('review_images', {
                'user_id': context.user_id,
                'order_id': context.order_id,
                'attachments': [dict(item) for item in context.attachments],
                'order_hint': ' '.join(
                    item for item in (context.product_name, context.product_category) if item
                ),
                'issue_hint': state.get('issue') or '',
                'skill_name': skill.name,
                'skill_version': skill.version,
                'skill_instructions': self._formal_skill_instructions('visual-review.md'),
            })
            facts = visual_facts(result)
            trace_step.details.update({
                'success': facts['visual_success'],
                'visual_verifiable': facts['visual_verifiable'],
                'missing_evidence_count': len(facts['missing_evidence']),
            })
        return {'visual_facts': facts}

    def review_synthesis(self, state: FormalReviewState) -> FormalReviewState:
        assessment = build_review_assessment(
            state['trusted_context'], state['policy_facts'], state['visual_facts']
        )
        escalation = FormalReviewSop.assess_escalation(
            assessment, minimum_review_confidence=self.minimum_review_confidence
        )
        review_mode = ESCALATED_REVIEW_MODE if escalation.required else SOP_REVIEW_MODE
        failure_reason = None
        with self._node_trace(state, 'review_synthesis') as trace_step:
            if not assessment.policy_success or not assessment.visual_success:
                proposal = FormalReviewSop.build_routine_proposal(assessment)
            elif escalation.required:
                try:
                    proposal = ComplexReviewSynthesizer(self.llm).synthesize(
                        state['trusted_context'], state.get('issue') or '', assessment
                    )
                except Exception:
                    failure_reason = 'review_synthesis_model_failed'
                    proposal = FormalReviewSop.build_routine_proposal(assessment)
            else:
                proposal = FormalReviewSop.build_routine_proposal(assessment)
            proposal = apply_deterministic_confidence(proposal, assessment)
            trace_step.details.update({
                'review_mode': review_mode,
                'policy_success': assessment.policy_success,
                'visual_success': assessment.visual_success,
                'confidence': proposal.confidence,
                'failure_reason': failure_reason,
            })
        return {
            'review_assessment': assessment,
            'review_proposal': proposal,
            'review_mode': review_mode,
            'escalation_reasons': list(escalation.reasons),
            'failure_reason': failure_reason,
        }

    def deterministic_gate(self, state: FormalReviewState) -> FormalReviewState:
        review = state['review_assessment']
        proposal = state['review_proposal']
        if state.get('failure_reason'):
            reason = str(state['failure_reason'])
        elif not review.visual_success:
            reason = 'evidence_service_failed'
        elif review.risk_signals:
            reason = 'evidence_risk_detected'
        elif not review.visual_verifiable:
            reason = 'visual_evidence_not_verifiable'
        elif review.visual_confidence < self.minimum_review_confidence:
            reason = 'visual_confidence_below_threshold'
        elif not review.policy_success or not review.trusted_policy_eligible:
            reason = 'policy_not_trusted'
        elif not review.policy_version_matched:
            reason = 'policy_version_not_matched'
        elif review.missing_evidence:
            reason = 'core_evidence_missing'
        elif proposal.confidence < self.minimum_review_confidence:
            reason = 'review_confidence_below_threshold'
        elif not self.auto_approve_enabled:
            reason = 'auto_approve_disabled'
        elif proposal.proposed_verdict != 'APPROVE' or review.evidence_consistent is not True:
            reason = 'approval_conditions_not_met'
        else:
            reason = ''
        action = 'MANUAL_REVIEW' if reason else 'SUBMIT_REVIEW'
        with self._node_trace(state, 'review_deterministic_gate') as trace_step:
            trace_step.details.update({
                'gate_action': action,
                'gate_reasons': [reason] if reason else [],
                'review_confidence': proposal.confidence,
            })
        return {
            'gate_action': action,
            'gate_reasons': [reason] if reason else [],
            'need_human': bool(reason),
        }

    def submit_review(self, state: FormalReviewState) -> FormalReviewState:
        return self._submit_verdict(state, "APPROVE")

    def submit_manual_review(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        return self._submit_verdict(state, "MANUAL_REVIEW_REQUIRED")

    def request_missing_evidence(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        evidence_request_skill = self._require_skill("evidence_collection")
        skill_versions = dict(state.get("skill_versions") or {})
        skill_versions[evidence_request_skill.name] = evidence_request_skill.version
        payload = state["payload"]
        context = state.get("trusted_context")
        missing = list(state.get("evidence_needed") or [])
        reply = (
            f"为便于继续审核，请补充：{'、'.join(missing)}。"
            if missing
            else "为便于继续审核，请补充相关问题凭证。"
        )
        arguments = {
            "user_id": context.user_id if context else payload.get("user_id"),
            "session_id": context.session_id if context else payload.get("session_id"),
            "ticket_id": context.ticket_id if context else payload.get("ticket_id"),
            "order_id": context.order_id if context else payload.get("order_id"),
            "review_request_id": str(payload.get("review_request_id") or ""),
            "evidence_revision": context.evidence_revision if context else 0,
            "assistant_reply": reply,
            "evidence_needed": missing,
        }
        with self._node_trace(
            state,
            "java_request_missing_evidence",
            missing_evidence_count=len(missing),
        ) as trace_step:
            self._raise_if_cancelled()
            result = self.tools.call("request_missing_evidence", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        AGENT_RUNTIME_METRICS.record_formal_review(
            action="request_evidence",
            success=result.ok,
        )
        trace = list(state.get("tool_trace") or [])
        trace.append(self._trace_entry(result, arguments))
        data = result.data if result.ok and isinstance(result.data, dict) else {}
        reject_reason = str(
            data.get("review_reject_reason")
            or data.get("reviewRejectReason")
            or ""
        ).upper()
        stale_evidence = reject_reason == "STALE_EVIDENCE"
        applied = bool(result.ok and not stale_evidence)
        return {
            "tool_trace": trace,
            "evidence_request_applied": applied,
            "evidence_request_outcome": reject_reason,
            "evidence_needed": missing,
            "skill_versions": skill_versions,
            "final_reply": (
                reply
                if applied
                else ""
                if stale_evidence
                else "补充凭证请求暂时无法确认，售后申请将转由人工继续核对。"
            ),
            "need_human": not result.ok and not stale_evidence,
            "failure_reason": (
                None
                if applied or stale_evidence
                else result.error_category or "evidence_request_failed"
            ),
            "gate_action": (
                "REQUEST_EVIDENCE"
                if applied
                else "STALE_EVIDENCE"
                if stale_evidence
                else "MANUAL_REVIEW"
            ),
        }

    def await_evidence(self, state: FormalReviewState) -> FormalReviewState:
        context = state.get("trusted_context")
        signal = interrupt(
            {
                "reason": "evidence_required",
                "review_id": str(state["payload"].get("review_request_id") or ""),
                "ticket_id": context.ticket_id if context else None,
                "evidence_revision": context.evidence_revision if context else 0,
                "evidence_needed": list(state.get("evidence_needed") or []),
            }
        )
        return {"resume_signal": dict(signal) if isinstance(signal, dict) else {}}

    def prepare_resumed_attempt(self, state: FormalReviewState) -> FormalReviewState:
        return {
            "trace_id": current_trace_id() or str(state.get("trace_id") or ""),
            "trusted_context": None,
            "ticket_data": {},
            "policy_query": "",
            "policy_facts": {},
            "visual_facts": {},
            "review_assessment": None,
            "review_proposal": None,
            "review_result": None,
            "gate_action": "",
            "gate_reasons": [],
            "evidence_needed": [],
            "evidence_request_applied": False,
            "evidence_request_outcome": "",
            "need_human": False,
            "failure_reason": None,
            "final_reply": "",
            "tool_trace": [],
            "review_mode": SOP_REVIEW_MODE,
            "escalation_reasons": [],
            "skill_versions": self._formal_skill_versions(),
        }

    def _submit_verdict(
        self,
        state: FormalReviewState,
        verdict: str,
    ) -> FormalReviewState:
        payload = state["payload"]
        context = state.get("trusted_context")
        review = state.get('review_assessment')
        proposal = state.get('review_proposal')
        arguments = {
            "user_id": context.user_id if context else payload.get("user_id"),
            "session_id": context.session_id if context else payload.get("session_id"),
            "ticket_id": context.ticket_id if context else payload.get("ticket_id"),
            "order_id": context.order_id if context else payload.get("order_id"),
            "review_request_id": str(payload.get("review_request_id") or ""),
            "expected_evidence_revision": (
                context.evidence_revision if context else 0
            ),
            "agent_architecture": "single_agent_skills_tools_retrieval",
            "skill_versions": state.get("skill_versions")
            or self._formal_skill_versions(),
            "context_version": context.context_version if context else None,
            "verdict": verdict,
            "ai_review_confidence": proposal.confidence if proposal else 0.0,
            "model_confidence": (
                proposal.model_confidence if proposal else 0.0
            ),
            "confidence_model_version": (
                proposal.confidence_model_version if proposal else None
            ),
            "confidence_breakdown": (
                proposal.confidence_breakdown if proposal else {}
            ),
            "reason": (
                proposal.reason
                if proposal
                else "智能审核无法形成可靠结论，转人工审核。"
            ),
            "evidence_needed": list(review.missing_evidence) if review else [],
            "visual_uncertain": not bool(review and review.visual_verifiable),
            "policy_uncertain": not bool(review and review.trusted_policy_eligible),
            "evidence_consistent": review.evidence_consistent if review else None,
            "visual_confidence": review.visual_confidence if review else 0.0,
            "risk_review_reasons": list(dict.fromkeys([
                *(state.get('gate_reasons') or []),
                *(state.get('escalation_reasons') or []),
                *(proposal.risk_reasons if proposal else ()),
                *(review.policy_issues if review else ()),
                *(review.visual_issues if review else ()),
            ])),
            "knowledge_retrieval_mode": review.retrieval_mode if review else None,
            "filter_level": review.filter_level if review else None,
            "reranker_succeeded": review.reranker_succeeded if review else False,
            "trusted_policy_eligible": review.trusted_policy_eligible if review else False,
            "policy_version": context.policy_version if context else None,
            "policy_match_score": review.policy_match_score if review else 0.0,
            "policy_citations": [dict(item) for item in review.citations] if review else [],
            "image_review": review.image_review if review else None,
            "specialist_assessments": {"review": review.to_dict()} if review else {},
        }
        step_name = (
            "java_submit_review"
            if verdict == "APPROVE"
            else "java_submit_manual_review"
        )
        with self._node_trace(
            state,
            step_name,
            verdict=verdict,
        ) as trace_step:
            self._raise_if_cancelled()
            result = self.tools.call("submit_ai_review", arguments)
            data = result.data if result.ok and isinstance(result.data, dict) else None
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                    "review_applied": bool(data and data.get("review_applied") is True),
                    "review_reject_reason": (
                        (data or {}).get("review_reject_reason")
                        if isinstance(data, dict)
                        else None
                    ),
                }
            )
        AGENT_RUNTIME_METRICS.record_formal_review(
            action=(
                "submit_review"
                if verdict == "APPROVE"
                else "manual_review"
            ),
            success=result.ok,
        )
        trace = list(state.get("tool_trace") or [])
        trace.append(self._trace_entry(result, arguments))
        data = result.data if result.ok and isinstance(result.data, dict) else None
        applied = bool(data and data.get("review_applied") is True)
        reject_reason = str((data or {}).get("review_reject_reason") or "").upper()
        if not applied and reject_reason == "STALE_EVIDENCE":
            return {
                "tool_trace": trace,
                "review_result": data,
                "final_reply": "",
                "need_human": False,
                "failure_reason": "stale_evidence",
            }
        actual = str(
            (data or {}).get("verdict")
            or (data or {}).get("ai_review_result")
            or verdict
        ).upper()
        if applied and actual == "APPROVE":
            reply = "您的售后申请已完成智能初审，当前已进入处理中。"
            need_human = False
        elif applied:
            reply = "您的售后申请需要人工进一步复核。"
            need_human = True
        else:
            reply = "智能初审结果暂时无法确认，将由人工继续核对。"
            need_human = True
        return {
            "tool_trace": trace,
            "review_result": data,
            "final_reply": reply,
            "need_human": need_human,
            "failure_reason": (
                state.get("failure_reason")
                or (
                    None
                    if applied
                    else result.error_category or "review_not_applied"
                )
            ),
        }

    @staticmethod
    def _raise_if_cancelled() -> None:
        event = _REVIEW_CANCEL_EVENT.get()
        if event is not None and event.is_set():
            raise TimeoutError("AI review was cancelled after the consumer deadline")

    @staticmethod
    def route_after_context(
        state: FormalReviewState,
    ) -> Literal["validate_review_inputs", "submit_manual_review"]:
        return (
            "validate_review_inputs"
            if state.get("trusted_context")
            and not state.get("failure_reason")
            else "submit_manual_review"
        )

    @staticmethod
    def route_after_input_validation(
        state: FormalReviewState,
    ) -> Literal["sop_plan", "request_missing_evidence"]:
        return (
            "request_missing_evidence"
            if state.get("evidence_needed")
            else "sop_plan"
        )

    @staticmethod
    def route_after_gate(state: FormalReviewState) -> Literal['submit_review', 'submit_manual_review']:
        return 'submit_review' if state.get('gate_action') == 'SUBMIT_REVIEW' else 'submit_manual_review'

    @staticmethod
    def route_after_evidence_request(
        state: FormalReviewState,
    ) -> Literal["await_evidence", "end", "submit_manual_review"]:
        if state.get("evidence_request_applied"):
            return "await_evidence"
        if state.get("evidence_request_outcome") == "STALE_EVIDENCE":
            return "end"
        return "submit_manual_review"

    @staticmethod
    def _trace_entry(
        result: ToolResult,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "tool": result.name,
            "arguments": arguments,
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "error_category": result.error_category,
            "retryable": result.retryable,
            "function_call_mode": "deterministic",
            "provider_tool_call_shape": "none",
        }

    @staticmethod
    def _trace_step(
        trace_recorder: TraceRecorder | None,
        name: str,
        **details: Any,
    ):
        return (
            trace_recorder.step(name, **details)
            if trace_recorder is not None
            else nullcontext(type("TraceDetails", (), {"details": {}})())
        )

    @contextmanager
    def _node_trace(
        self,
        state: FormalReviewState,
        name: str,
        **details: Any,
    ):
        trace = _ACTIVE_REVIEW_TRACE.get()
        with bind_trace_id(trace.trace_id if trace else None):
            with self._trace_step(trace, name, **details) as trace_step:
                yield trace_step

    @staticmethod
    def _ticket_payload(ticket: dict[str, Any]) -> dict[str, Any] | None:
        if not ticket:
            return None
        return {
            "ticket_id": str(ticket.get("ticket_id") or "") or None,
            "ticket_no": str(ticket.get("ticket_no") or "") or None,
            "status": str(ticket.get("status") or "").lower(),
            "order_id": str(ticket.get("order_id") or "") or None,
            "existing": bool(ticket.get("existing")),
        }

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        to_dict = getattr(value, "to_dict", None)
        return to_dict() if callable(to_dict) else None

    def _require_skill(self, stage: str) -> AgentSkill:
        skill = self.skills.select(stage)
        if skill is None:
            raise RuntimeError(f"required formal review skill is missing: {stage}")
        return skill

    def _formal_skill_versions(self) -> dict[str, str]:
        return {
            self._formal_review_skill_definition.name: (
                self._formal_review_skill_definition.version
            ),
        }

    def _formal_skill_instructions(self, reference: str) -> str:
        reference_instructions = self.skills.load_reference(
            self._formal_review_skill_definition.name,
            reference,
        )
        return (
            f"按需加载的工作流参考（{reference}）：\n"
            f"{reference_instructions}"
        )
