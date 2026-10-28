"""会话 Agent：模型自主选工具，工作流守住全部业务边界。

与正式审核的分工：

* **正式审核**是确定性图：控制流写死，模型只在综合节点提供一次输入。
* **会话咨询**是受控 ReAct 图：模型决定查什么，但控制流仍然有硬上界。

这里有四条边界是代码强制的，不依赖提示词：

1. 模型只看得见只读工具（角色白名单），``submit_ai_review`` 对它不存在。
2. 所有写操作（落库消息、补证请求、转人工）由工作流执行，不由模型调用。
3. 可信政策判定由代码做，模型不能自己宣布某条政策可信；拿不到可信政策就转人工。
4. 规划轮次、工具调用次数、重复调用次数都有硬上界。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import copy_context
from dataclasses import dataclass, field
import json
import os
import re
import time
from typing import Any, Optional, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from ....application.rag_query_rewrite import RagQueryRewriteService, RagRewriteError
from ....application.rag_retrieval_policy import RagRetrievalPolicy
from ....infrastructure.agent_metrics import AGENT_RUNTIME_METRICS
from ....infrastructure.request_tracing import TraceRecorder, bind_trace_id
from ....providers.llm_client import get_llm_client
from ....tools import AgentToolRegistry, ToolResult
from ...facts import CaseContext, CaseContextBuilder, trusted_policy_hits, user_claim_facts
from ...safety_guards import is_explicit_human_request
from .planner import ConsultationPlanner
from .prompts import planner_system_prompt, planner_user_message
from .context_projector import ContextProjector
from .context_assembler import ContextAssembler, ContextBudgetExceeded


class ChatLlm(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def generate_structured(self, *, system_prompt: str, user_prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


class ChatTools(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...


class ChatRagRewrite(Protocol):
    def evaluate(self, **kwargs: Any) -> Any:
        ...


class ConsultationState(TypedDict, total=False):
    payload: dict[str, Any]
    trace_recorder: Optional[TraceRecorder]
    builder: CaseContextBuilder
    messages: list[dict[str, Any]]
    plan_round: int
    tool_call_count: int
    call_signatures: list[str]
    planned_calls: list[dict[str, Any]]
    trusted_hits: list[dict[str, Any]]
    knowledge: dict[str, Any]
    resolved_order_id: str
    resolved_ticket_id: str
    retrieval_queries: list[str]
    rewrite_used: bool
    final_reply: str
    evidence_needed: list[str]
    issue_type: str
    clarification_needed: bool
    visual_review: dict[str, Any]
    need_human: bool
    stop_reason: str
    next_action: str
    tool_trace: list[dict[str, Any]]
    seen_fact_keys: list[tuple[str, str, str, str]]


#: 这些工具的用户归属由可信载荷决定，模型既不提供也不能伪造。
_USER_SCOPED_TOOLS = frozenset(
    {
        "search_user_orders",
        "get_order_detail",
        "get_existing_after_sales",
        "get_after_sales_ticket",
    }
)

#: 这些工具需要订单号。
_ORDER_SCOPED_TOOLS = frozenset(
    {"get_order_detail", "get_existing_after_sales"}
)

#: 这些工具需要工单号。
_TICKET_SCOPED_TOOLS = frozenset({"get_after_sales_ticket"})

#: 模型不得自行指定的字段：归属与政策上下文由可信载荷决定。
_TRUSTED_ONLY_ARGUMENTS = frozenset(
    {"user_id", "order_id", "ticket_id", "merchant_code", "policy_version", "as_of_time"}
)


@dataclass
class ConsultationWorkflow:
    """Answer policy consultations with a bounded, model-driven tool loop."""

    tools: ChatTools = field(default_factory=AgentToolRegistry)
    llm: ChatLlm = field(default_factory=get_llm_client)
    rag_rewrite_service: ChatRagRewrite | None = None
    max_plan_rounds: int = 2
    max_tool_calls: int = 8
    max_parallel_tools: int = 4
    max_duplicate_tool_calls: int = 1

    def __post_init__(self) -> None:
        if self.rag_rewrite_service is None:
            self.rag_rewrite_service = RagQueryRewriteService(llm=self.llm)
        self._retrieval_policy = RagRetrievalPolicy()
        self._planner = ConsultationPlanner(llm=self.llm)
        self._assembler = ContextAssembler(output_reserve=self._planner.max_tokens)
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        trace = trace_recorder if isinstance(trace_recorder, TraceRecorder) else None
        bind_llm = getattr(self.llm, "bind_trace", None)
        if callable(bind_llm):
            bind_llm(trace)
        try:
            with bind_trace_id(trace.trace_id if trace else None):
                return self._handle_core(payload, trace)
        finally:
            if callable(bind_llm):
                bind_llm(None)

    def _handle_core(
        self,
        payload: dict[str, Any],
        trace_recorder: TraceRecorder | None,
    ) -> dict[str, Any]:
        message = str(payload.get("message") or "").strip()
        with self._trace_step(
            trace_recorder,
            "chat_validate_input",
            has_message=bool(message),
            has_session=bool(payload.get("session_id")),
            has_order=bool(payload.get("order_id")),
        ):
            if not message:
                return self._result(
                    reply="请描述您需要咨询的售后政策问题。",
                    session_mode="AI",
                    need_human=False,
                    trace=[],
                    raw={"handoff_reason": None},
                    payload=payload,
                )

        if self._explicit_human_request(payload):
            with self._trace_step(
                trace_recorder,
                "chat_explicit_handoff",
                reason="explicit_human_request",
            ):
                return self._handoff(payload, [], "explicit_human_request", trace_recorder)

        builder = CaseContextBuilder()
        builder.add_facts(user_claim_facts(message))
        initial_trace: list[dict[str, Any]] = []
        initial_signatures: list[str] = []
        verified_order_id = ""
        verified_ticket_id = ""
        order_id = str(payload.get("order_id") or "").strip()
        if order_id:
            arguments = {"user_id": payload.get("user_id"), "order_id": order_id}
            with self._trace_step(trace_recorder, "consultation_load_order") as trace_step:
                try:
                    order = self.tools.call("get_order_detail", arguments)
                except Exception as exc:  # noqa: BLE001 - Java ownership check failed
                    order = ToolResult(
                        ok=False, name="get_order_detail", error=str(exc),
                        error_category="tool_error",
                    )
                trace_step.details.update({"ok": order.ok, "error_category": order.error_category})
            initial_trace.append({
                **self._trace_entry(order, arguments),
                "reason": "核验所选订单归属与商家政策上下文",
            })
            if not (order.ok and isinstance(order.data, dict) and order_id in {
                str(order.data.get("order_id") or ""),
                str(order.data.get("order_no") or ""),
            }):
                return self._handoff(
                    payload, initial_trace, "order_context_unavailable", trace_recorder,
                )
            verified_order_id = str(order.data["order_id"])
            builder.add_tool_result("get_order_detail", order.data)
            initial_signatures.append(
                "get_order_detail:" + json.dumps(
                    {**arguments, "order_id": verified_order_id},
                    ensure_ascii=False, sort_keys=True, default=str,
                )
            )
        ticket_id = str(payload.get("ticket_id") or "").strip()
        if ticket_id:
            arguments = {"user_id": payload.get("user_id"), "ticket_id": ticket_id}
            if verified_order_id:
                arguments["order_id"] = verified_order_id
            with self._trace_step(trace_recorder, "consultation_load_ticket") as trace_step:
                try:
                    ticket = self.tools.call("get_after_sales_ticket", arguments)
                except Exception as exc:  # noqa: BLE001 - Java ownership validation failed
                    ticket = ToolResult(ok=False, name="get_after_sales_ticket",
                                        error=str(exc), error_category="tool_error")
                trace_step.details.update({"ok": ticket.ok, "error_category": ticket.error_category})
            initial_trace.append({**self._trace_entry(ticket, arguments),
                                  "reason": "核验工单归属、政策版本与证据版本"})
            data = ticket.data if ticket.ok and isinstance(ticket.data, dict) else {}
            if (ticket_id not in {str(data.get("ticket_id") or ""), str(data.get("ticket_no") or "")}
                    or (verified_order_id and str(data.get("order_id") or "") != verified_order_id)):
                return self._handoff(payload, initial_trace, "ticket_context_unavailable", trace_recorder)
            verified_ticket_id = str(data.get("ticket_id") or ticket_id)
            builder.add_tool_result("get_after_sales_ticket", data)
            initial_signatures.append("get_after_sales_ticket:" + json.dumps(
                {"user_id": payload.get("user_id"), "ticket_id": verified_ticket_id,
                 **({"order_id": verified_order_id} if verified_order_id else {})},
                ensure_ascii=False, sort_keys=True, default=str,
            ))
        state: ConsultationState = {
            "payload": payload,
            "trace_recorder": trace_recorder,
            "builder": builder,
            "messages": [],
            "plan_round": 0,
            "tool_call_count": 0,
            "call_signatures": initial_signatures,
            "resolved_order_id": verified_order_id,
            "resolved_ticket_id": verified_ticket_id,
            "trusted_hits": [],
            "knowledge": {},
            "visual_review": {},
            "retrieval_queries": [],
            "rewrite_used": False,
            "tool_trace": initial_trace,
            "seen_fact_keys": [],
        }
        final_state = self._graph.invoke(state)
        return self._finish(final_state, payload, trace_recorder)

    # ------------------------------------------------------------------
    # 图
    # ------------------------------------------------------------------

    def _build_graph(self) -> Any:
        graph = StateGraph(ConsultationState)
        graph.add_node("plan", self.plan)
        graph.add_node("act", self.act)
        graph.add_node("finalize", self.finalize)
        graph.set_entry_point("plan")
        graph.add_conditional_edges(
            "plan",
            self.route_after_plan,
            {"plan": "plan", "act": "act", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "act",
            self.route_after_act,
            {"plan": "plan", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    def route_after_plan(self, state: ConsultationState) -> str:
        return str(state.get("next_action") or "finalize")

    def route_after_act(self, state: ConsultationState) -> str:
        if int(state.get("plan_round") or 0) >= self.max_plan_rounds:
            return "finalize"
        return "plan"

    # ------------------------------------------------------------------
    # 节点：规划
    # ------------------------------------------------------------------

    def plan(self, state: ConsultationState) -> ConsultationState:
        plan_round = int(state.get("plan_round") or 0)
        if plan_round >= self.max_plan_rounds:
            return {
                **state,
                "stop_reason": "plan_budget_exhausted",
                "need_human": True,
                "next_action": "finalize",
            }
        payload = state["payload"]
        builder: CaseContextBuilder = state["builder"]
        context = builder.build()
        trusted = list(state.get("trusted_hits") or [])
        messages = list(state.get("messages") or [])
        context_mode = os.getenv("AGENT_CONTEXT_MODE", "active").lower()
        if context_mode not in {"legacy", "shadow", "active"}:
            context_mode = "active"
        estimate = 0
        if context_mode == "legacy":
            messages.append(planner_user_message(
                payload, context, trusted_hit_count=len(trusted),
                tool_calls_made=int(state.get("tool_call_count") or 0),
                plan_round=plan_round + 1,
            ))
        else:
            view = self._assembler.view(
                payload, context, round_no=plan_round + 1,
                seen_fact_keys=set(state.get("seen_fact_keys") or []),
                resolved_order_id=str(state.get("resolved_order_id") or ""),
                resolved_ticket_id=str(state.get("resolved_ticket_id") or ""),
            )
            try:
                prepared, estimate, omissions = self._assembler.prepare(
                    system_prompt=self._system_prompt(plan_round + 1), tool_schemas=self._planner.model_tools,
                    messages=messages, view=view,
                    metadata={"trusted_policy_hit_count": len(trusted),
                              "tool_calls_made": int(state.get("tool_call_count") or 0),
                              "plan_round": plan_round + 1},
                )
            except ContextBudgetExceeded:
                if context_mode != "shadow":
                    return {**state, "stop_reason": "context_budget_exhausted",
                            "need_human": True, "next_action": "finalize"}
                prepared, estimate, omissions = [], 0, ["shadow_budget_exhausted"]
            if context_mode == "shadow":
                messages.append(planner_user_message(
                    payload, context, trusted_hit_count=len(trusted),
                    tool_calls_made=int(state.get("tool_call_count") or 0),
                    plan_round=plan_round + 1,
                ))
            else:
                messages = prepared
            if state.get("trace_recorder"):
                with self._trace_step(state["trace_recorder"], "context_assemble",
                                      estimated_tokens=estimate, omitted=omissions):
                    pass
            state["seen_fact_keys"] = [
                (fact.claim_key, fact.source_ref, repr(fact.value), fact.context_version)
                for fact in context.facts
            ]
        try:
            decision = self._planner.plan(
                system_prompt=self._system_prompt(plan_round + 1),
                messages=messages,
                trace_recorder=state.get("trace_recorder"),
            )
        except Exception as exc:  # noqa: BLE001 - a planner failure must not 500
            return {
                **state,
                "messages": messages,
                "stop_reason": f"planner_failed:{exc.__class__.__name__}",
                "need_human": True,
                "next_action": "finalize",
            }

        usage = decision.usage or {}
        actual_input = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        if context_mode == "active" and actual_input:
            self._assembler.calibrate(estimate, actual_input)
        if state.get("trace_recorder") and actual_input:
            with self._trace_step(state["trace_recorder"], "context_usage",
                                  estimated_input_tokens=estimate,
                                  actual_input_tokens=actual_input,
                                  estimation_error=actual_input - estimate):
                pass

        messages = [*messages, decision.assistant_message]
        actions = list(decision.actions)
        handoff = [action for action in actions if action.get("action") == "human_handoff"]
        finals = [action for action in actions if action.get("action") == "final_reply"]
        tool_calls = [action for action in actions if action.get("action") == "tool_call"]

        if handoff:
            action = handoff[0]
            return {
                **state,
                "messages": messages,
                "final_reply": str(action.get("assistant_reply") or "").strip(),
                "need_human": True,
                "stop_reason": "model_requested_handoff",
                "next_action": "finalize",
            }

        if finals:
            action = finals[0]
            reply = str(action.get("assistant_reply") or "").strip()
            evidence = [str(item) for item in (action.get("evidence_needed") or [])]
            wants_human = bool(action.get("need_human"))
            if action.get("clarification_needed") and not wants_human:
                return {
                    **state, "messages": messages,
                    "final_reply": "请具体描述商品出现的问题现象、发生时间和使用场景吗？",
                    "clarification_needed": True,
                    "stop_reason": "clarification_requested", "next_action": "finalize",
                }
            if trusted or wants_human:
                return {
                    **state,
                    "messages": messages,
                    "final_reply": reply,
                    "evidence_needed": evidence,
                    "issue_type": str(action.get("issue_type") or ""),
                    "need_human": wants_human,
                    "stop_reason": "answered",
                    "next_action": "finalize",
                }
            # 首轮提前答复时，由工作流补一次政策检索，再给模型唯一的再规划机会。
            messages = [
                *messages,
                self._observation(
                    str(action.get("tool_call_id") or "final_reply"),
                    "final_reply",
                    {
                        "ok": False,
                        "error": "policy_evidence_required",
                        "instruction": (
                            "尚未取得可信政策证据，不能直接作答。"
                            "请先调用 retrieve_knowledge 检索适用政策后再答复。"
                        ),
                    },
                ),
            ]
            if plan_round > 0:
                return {
                    **state, "messages": messages, "need_human": True,
                    "stop_reason": "policy_evidence_required", "next_action": "finalize",
                }
            call_id = "guard-policy-retrieval"
            query = str(payload.get("message") or "").strip()
            tool_arguments = {
                "query": query,
                "reason": "首轮答复缺少可信政策依据，先核对适用政策",
            }
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id, "type": "function",
                    "function": {"name": "retrieve_knowledge", "arguments": tool_arguments},
                }],
            })
            return {
                **state, "messages": messages, "plan_round": 1,
                "planned_calls": [{
                    "action": "tool_call", "tool_name": "retrieve_knowledge",
                    "tool_arguments": tool_arguments, "tool_call_id": call_id,
                }],
                "stop_reason": "policy_evidence_required", "next_action": "act",
            }

        if not tool_calls:
            return {
                **state,
                "messages": messages,
                "stop_reason": "planner_returned_no_action",
                "need_human": True,
                "next_action": "finalize",
            }

        if any(not str((action.get("tool_arguments") or {}).get("reason") or "").strip()
               for action in tool_calls):
            return {
                **state, "messages": messages, "need_human": True,
                "stop_reason": "missing_tool_reason", "next_action": "finalize",
            }

        return {
            **state,
            "messages": messages,
            "planned_calls": tool_calls,
            "plan_round": plan_round + 1,
            "next_action": "act",
        }

    # ------------------------------------------------------------------
    # 节点：执行
    # ------------------------------------------------------------------

    def act(self, state: ConsultationState) -> ConsultationState:
        builder: CaseContextBuilder = state["builder"]
        calls = list(state.get("planned_calls") or [])
        messages = list(state.get("messages") or [])
        signatures = list(state.get("call_signatures") or [])
        tool_call_count = int(state.get("tool_call_count") or 0)
        tool_trace = list(state.get("tool_trace") or [])
        retrieval_queries = list(state.get("retrieval_queries") or [])

        budget = max(0, self.max_tool_calls - tool_call_count)
        executable: list[tuple[str, str, dict[str, Any], str, str]] = []
        seen_in_round: set[str] = set()
        for action in calls:
            name = str(action.get("tool_name") or "")
            call_id = str(action.get("tool_call_id") or "")
            reason = str((action.get("tool_arguments") or {}).get("reason") or "").strip()
            arguments = self._tool_arguments(name, action.get("tool_arguments") or {}, state)
            if name == "review_images" and not state["payload"].get("attachments"):
                messages.append(self._observation(call_id or name, name,
                                                  {"ok": False, "error_category": "no_attachments"}))
                continue
            signature = f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)}"
            if signature in seen_in_round or signatures.count(signature) >= self.max_duplicate_tool_calls:
                messages.append(
                    self._observation(
                        call_id or name,
                        name,
                        {"ok": False, "error": "duplicate_tool_call_skipped"},
                    )
                )
                continue
            if len(executable) >= budget:
                messages.append(
                    self._observation(
                        call_id or name,
                        name,
                        {"ok": False, "error": "tool_call_budget_exhausted"},
                    )
                )
                continue
            executable.append((call_id, name, arguments, signature, reason))
            seen_in_round.add(signature)

        results = self._execute(executable)
        knowledge = state.get("knowledge") or {}
        trusted = list(state.get("trusted_hits") or [])
        rewrite_used = bool(state.get("rewrite_used"))
        visual_review = dict(state.get("visual_review") or {})

        resolved_order_id = str(state.get("resolved_order_id") or "")
        resolved_ticket_id = str(state.get("resolved_ticket_id") or "")
        for call_id, name, arguments, signature, reason in executable:
            result = results.get(call_id, None)
            if result is None:
                continue
            signatures.append(signature)
            tool_call_count += 1
            tool_trace.append({**self._trace_entry(result, arguments), "reason": reason})
            AGENT_RUNTIME_METRICS.record_tool(result.name, result.ok, result.error_category)
            builder.add_tool_result(result.name, result.data if result.ok else None)
            if name == "retrieve_knowledge":
                query = str(arguments.get("query") or "").strip()
                if query:
                    retrieval_queries.append(query)
                if result.ok and isinstance(result.data, dict):
                    knowledge = result.data
                    trusted = trusted_policy_hits(knowledge)
            if name == "review_images" and result.ok and isinstance(result.data, dict):
                visual_review = result.data
            if name == "search_user_orders" and result.ok:
                if not state["payload"].get("order_id"):
                    resolved_order_id = _first_order_id(result.data) or resolved_order_id
            if name in {"get_existing_after_sales", "get_after_sales_ticket"} and result.ok:
                resolved_ticket_id = _first_ticket_id(result.data) or resolved_ticket_id
            messages.append(
                self._observation(
                    call_id,
                    name,
                    self._observation_payload(result),
                )
            )

        if (
            not trusted
            and not rewrite_used
            and knowledge
            and not self._retrieval_policy.is_infrastructure_failure(knowledge)
        ):
            knowledge, trusted, rewrite_trace = self._rewrite_and_retrieve(
                state,
                knowledge,
                retrieval_queries,
                trace_recorder=state.get("trace_recorder"),
            )
            tool_trace.extend(rewrite_trace)
            builder.add_tool_result("retrieve_knowledge", knowledge)
            if trusted:
                messages.append(
                    self._observation(
                        "rewrite",
                        "retrieve_knowledge_multi",
                        {
                            "ok": True,
                            "error": "policy_evidence_required",
                            "instruction": (
                                "已按改写查询补充检索，可信政策证据现已可用，"
                                "请据此作答。"
                            ),
                        },
                    )
                )

        return {
            **state,
            "messages": messages,
            "call_signatures": signatures,
            "tool_call_count": tool_call_count,
            "tool_trace": tool_trace,
            "knowledge": knowledge,
            "trusted_hits": trusted,
            "visual_review": visual_review,
            "retrieval_queries": retrieval_queries,
            "rewrite_used": rewrite_used or bool(trusted),
            "resolved_order_id": resolved_order_id,
            "resolved_ticket_id": resolved_ticket_id,
            "planned_calls": [],
        }

    # ------------------------------------------------------------------
    # 可信参数注入
    # ------------------------------------------------------------------

    def _tool_arguments(
        self,
        name: str,
        model_arguments: dict[str, Any],
        state: ConsultationState,
    ) -> dict[str, Any]:
        """Resolve the arguments of one tool call.

        Ownership and policy context come from the trusted payload, never from
        the model: the model may only choose *what* to ask for, not *whose*
        data to ask about.
        """
        payload = state.get("payload") or {}
        arguments = {
            key: value
            for key, value in dict(model_arguments or {}).items()
            if key not in _TRUSTED_ONLY_ARGUMENTS and key != "reason"
        }
        if name in _USER_SCOPED_TOOLS:
            arguments["user_id"] = payload.get("user_id")
        if name in _ORDER_SCOPED_TOOLS:
            order_id = self._resolved_order_id(state)
            if order_id:
                arguments["order_id"] = order_id
        if name in _TICKET_SCOPED_TOOLS:
            ticket_id = self._resolved_ticket_id(state)
            if ticket_id:
                arguments["ticket_id"] = ticket_id
            order_id = str(state.get("resolved_order_id") or "")
            if order_id:
                arguments["order_id"] = order_id
        if name == "retrieve_knowledge":
            arguments.update(self._trusted_retrieval_filters(state))
        if name == "get_merchant_policy":
            merchant_code = self._trusted_merchant_code(state)
            if merchant_code:
                arguments["merchant_code"] = merchant_code
        if name == "review_images":
            arguments = {
                "attachments": list(payload.get("attachments") or []),
                "order_hint": str(payload.get("order_id") or ""),
                "issue_hint": str(payload.get("message") or ""),
            }
        return arguments

    def _resolved_order_id(self, state: ConsultationState) -> str:
        payload = state.get("payload") or {}
        for candidate in (
            state.get("resolved_order_id"),
            payload.get("order_id"),
        ):
            if candidate:
                return str(candidate)
        return ""

    def _resolved_ticket_id(self, state: ConsultationState) -> str:
        payload = state.get("payload") or {}
        for candidate in (state.get("resolved_ticket_id"), payload.get("ticket_id")):
            if candidate:
                return str(candidate)
        return ""

    def _trusted_merchant_code(self, state: ConsultationState) -> str:
        order = self._verified_order_value(state, "order.merchant_code")
        if order:
            return order
        ticket = state["builder"].build().best_fact("ticket.merchant_code")
        return str(ticket.value) if ticket and ticket.trust == "verified" else ""

    def _verified_order_value(self, state: ConsultationState, claim_key: str) -> str:
        order_id = self._resolved_order_id(state)
        facts = state["builder"].build().facts
        refs = {
            fact.source_ref for fact in facts
            if fact.claim_key == "order.id" and str(fact.value) == order_id
            and fact.trust == "verified"
        }
        return next((
            str(fact.value) for fact in facts
            if fact.claim_key == claim_key and fact.source_ref in refs
            and fact.trust == "verified"
        ), "")

    def _trusted_retrieval_filters(self, state: ConsultationState) -> dict[str, Any]:
        """The policy filters the model may not choose for itself."""
        filters: dict[str, Any] = {"source_type": "after_sales_policy", "top_k": 5}
        merchant_code = self._trusted_merchant_code(state)
        if merchant_code:
            filters["merchant_code"] = merchant_code
        category = self._verified_order_value(state, "order.category")
        if not category:
            ticket_category = state["builder"].build().best_fact("ticket.category")
            category = str(ticket_category.value) if ticket_category and ticket_category.trust == "verified" else ""
        if category:
            filters["product_category"] = category
        ticket = state["builder"].build().best_fact("ticket.policy_version")
        policy_version = ticket.value if ticket and ticket.trust == "verified" else None
        if policy_version:
            filters["policy_version"] = policy_version
        applied = state["builder"].build().best_fact("ticket.applied_at")
        business_time = (str(applied.value) if applied and applied.trust == "verified"
                         else self._verified_order_value(state, "order.created_at"))
        if business_time:
            filters["as_of_time"] = business_time
        return filters

    def _execute(
        self,
        executable: list[tuple[str, str, dict[str, Any], str, str]],
    ) -> dict[str, ToolResult]:
        """Run the planned read-only calls; independent calls run in parallel."""
        if not executable:
            return {}
        workers = max(1, min(self.max_parallel_tools, len(executable)))

        def run(item: tuple[str, str, dict[str, Any], str, str]) -> tuple[str, ToolResult]:
            call_id, name, arguments, _, _ = item
            try:
                result = self.tools.call(name, arguments)
            except Exception as exc:  # noqa: BLE001 - a tool crash is a failed tool
                result = ToolResult(
                    ok=False,
                    name=name,
                    error=f"{exc.__class__.__name__}: {exc}",
                    error_code="TOOL_EXECUTION_ERROR",
                    error_category="tool_error",
                )
            return call_id, result

        if workers == 1:
            return dict(run(item) for item in executable)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(copy_context().run, run, item)
                for item in executable
            ]
            return dict(future.result() for future in futures)

    # ------------------------------------------------------------------
    # 节点：收尾判定
    # ------------------------------------------------------------------

    def finalize(self, state: ConsultationState) -> ConsultationState:
        trusted = list(state.get("trusted_hits") or [])
        need_human = bool(state.get("need_human"))
        reply = str(state.get("final_reply") or "").strip()
        stop_reason = str(state.get("stop_reason") or "")
        if not trusted and not need_human and not state.get("clarification_needed"):
            # 硬边界：没有可信政策证据就不作答。
            need_human = True
            reply = ""
            stop_reason = stop_reason or "knowledge_not_trusted"
        if not reply and not need_human:
            # 规划预算用尽仍未收口：只能转人工，不能硬答。
            need_human = True
            stop_reason = stop_reason or (
                "plan_budget_exhausted"
                if int(state.get("plan_round") or 0) >= self.max_plan_rounds
                else "empty_answer"
            )
        if need_human and not stop_reason:
            stop_reason = "handoff_required"
        return {
            **state,
            "need_human": need_human,
            "final_reply": reply,
            "stop_reason": stop_reason,
        }

    # ------------------------------------------------------------------
    # 收尾：写操作由工作流执行
    # ------------------------------------------------------------------

    def _finish(
        self,
        state: ConsultationState,
        payload: dict[str, Any],
        trace_recorder: TraceRecorder | None,
    ) -> dict[str, Any]:
        tool_trace = list(state.get("tool_trace") or [])
        context = state["builder"].build()
        changed_after_planning = False
        if context.conflicts and int(state.get("tool_call_count") or 0) < self.max_tool_calls:
            conflict = context.conflicts[0]
            kind = conflict.claim_key.split(".", 1)[0]
            tool_name = {"order": "get_order_detail", "ticket": "get_after_sales_ticket"}.get(kind)
            identifier = (state.get("resolved_order_id") if kind == "order"
                          else state.get("resolved_ticket_id"))
            if tool_name and identifier:
                arguments = {"user_id": payload.get("user_id"),
                             "order_id" if kind == "order" else "ticket_id": identifier}
                started = time.perf_counter()
                try:
                    refreshed = self.tools.call(tool_name, arguments)
                except Exception as exc:  # noqa: BLE001
                    refreshed = ToolResult(ok=False, name=tool_name,
                                           error_category="tool_error", error=str(exc))
                tool_trace.append({**self._trace_entry(refreshed, arguments),
                                   "reason": "事实冲突，单次权威重查",
                                   "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
                if refreshed.ok and isinstance(refreshed.data, dict):
                    state["builder"].add_tool_result(tool_name, refreshed.data)
                    for fact in state["builder"].facts:
                        if fact.claim_key == conflict.claim_key and fact.source_kind == kind:
                            current = next((item for item in state["builder"].facts
                                            if item.claim_key == conflict.claim_key
                                            and item.source_kind == kind
                                            and item.value == refreshed.data.get(conflict.claim_key.split(".", 1)[1])), None)
                            if current:
                                state["builder"].confirm_current(
                                    kind, fact.source_ref, conflict.claim_key, current.value,
                                    str(refreshed.data.get("context_version") or ""))
                            break
                    context = state["builder"].build()
                    changed_after_planning = not context.conflicts
        if context.conflicts or context.discrepancies:
            return self._handoff(
                payload, tool_trace, "case_fact_conflict", trace_recorder, context,
            )
        if changed_after_planning:
            return self._handoff(
                payload, tool_trace, "context_changed_after_planning", trace_recorder, context,
            )
        if state.get("need_human"):
            return self._handoff(
                payload,
                tool_trace,
                str(state.get("stop_reason") or "knowledge_not_trusted"),
                trace_recorder,
            )
        reply = str(state.get("final_reply") or "").strip()
        if not reply:
            return self._handoff(
                payload,
                tool_trace,
                "empty_answer",
                trace_recorder,
            )
        evidence_needed = [str(item) for item in (state.get("evidence_needed") or [])]
        if evidence_needed:
            selected = self._select_evidence(evidence_needed, state, payload)
            if selected is None:
                return self._handoff(
                    payload, tool_trace, "evidence_request_unverified", trace_recorder,
                )
            question = (
                f"现有凭证未能清楚呈现{self._issue_label(state)}，请补充可核验的{selected}吗？"
                if payload.get("attachments")
                else f"为核验您描述的{self._issue_label(state)}，请补充能清楚呈现问题现象的{selected}吗？"
            )
            return self._request_evidence(
                payload,
                tool_trace,
                self._ground_reply(question, state, context),
                [selected],
                state,
                trace_recorder,
            )
        if not state.get("clarification_needed"):
            reply = self._ground_reply(reply, state, context)
        return self._persist_answer(
            payload,
            tool_trace,
            reply,
            state,
            trace_recorder,
        )

    @staticmethod
    def _select_evidence(
        proposed: list[str], state: ConsultationState, payload: dict[str, Any],
    ) -> str | None:
        required = {
            item.strip(): item.strip()
            for item in state["builder"].policy_evidence_required()
            if item.strip()
        }
        for hit in state.get("trusted_hits") or []:
            for sentence in re.split(r"[。；;\n]", str(hit.get("snippet") or "")):
                if re.search(r"无需|不需要|不必|不要求", sentence):
                    continue
                if re.search(r"需|应|须|要求|请", sentence) and re.search(
                    r"提供|提交|上传|补充", sentence,
                ):
                    for item in proposed:
                        if item.strip() and item.strip() in sentence:
                            required[item.strip()] = item.strip()
        selected = next((required[item.strip()] for item in proposed if item.strip() in required), None)
        if not selected:
            return None
        if not payload.get("attachments"):
            return selected
        review = state.get("visual_review") or {}
        if review.get("success") is not True:
            return None
        missing = {str(item).strip() for item in review.get("missing_visual_evidence") or []}
        if missing and selected not in missing:
            return None
        insufficient = bool(
            missing
            or review.get("verification_limitations")
            or review.get("evidence_relevant") is False
            or review.get("evidence_consistent") is False
        )
        return selected if insufficient else None

    @staticmethod
    def _issue_label(state: ConsultationState) -> str:
        labels = {
            "functional_issue": "功能异常",
            "physical_damage": "外观破损",
            "wrong_item": "商品不符",
            "missing_part": "配件缺失",
            "logistics": "物流问题",
        }
        review = state.get("visual_review") or {}
        categories = review.get("evidence_categories") or []
        kind = str(
            categories[0]
            if isinstance(categories, (list, tuple)) and categories
            else state.get("issue_type") or ""
        )
        return labels.get(kind, "问题现象")

    def _ground_reply(
        self, reply: str, state: ConsultationState, context: CaseContext,
    ) -> str:
        answer_sources = self._answer_sources(state, context)
        sources: list[str] = []
        for fact in answer_sources["facts"]:
            kind = "订单" if fact["source_kind"] == "order" else "工单"
            sources.append(
                f"{kind} {fact['source_ref']} 状态 {fact['value']}"
                f"（核验于 {fact['observed_at']}）"
            )
        for citation in answer_sources["policy_citations"]:
            excerpt = str(citation.get("policy_excerpt") or "")[:100]
            sources.append(
                f"政策 {citation['source_code']} / {citation.get('chunk_id') or citation.get('document_id')}"
                + (f"：「{excerpt}」" if excerpt else "")
            )
        return f"{reply}\n核验依据：{'；'.join(sources)}。" if sources else reply

    def _answer_sources(
        self, state: ConsultationState, context: CaseContext | None = None,
    ) -> dict[str, Any]:
        context = context or state["builder"].build()
        order_id = str(state.get("resolved_order_id") or state["payload"].get("order_id") or "")
        order_refs = {
            fact.source_ref for fact in context.facts
            if fact.claim_key == "order.id" and str(fact.value) == order_id
        }
        ticket_id = str(state.get("resolved_ticket_id") or state["payload"].get("ticket_id") or "")
        ticket_refs = {
            fact.source_ref for fact in context.facts
            if fact.claim_key == "ticket.id" and str(fact.value) == ticket_id
        }
        facts = [
            fact.to_dict() for fact in context.facts
            if fact.trust == "verified" and (
                fact.claim_key == "order.status" and fact.source_ref in order_refs
                or fact.claim_key == "ticket.status" and fact.source_ref in ticket_refs
            )
        ][:3]
        policy_facts = {
            fact.source_ref: fact for fact in context.facts
            if fact.claim_key.startswith("policy.evidence.")
        }
        citations = []
        for citation in self._citations(list(state.get("trusted_hits") or []))[:2]:
            item = dict(citation)
            ref = f"{item['source_code']}@{item.get('chunk_id') or item.get('document_id')}"
            policy_fact = policy_facts.get(ref)
            if policy_fact:
                item["policy_excerpt"] = str(policy_fact.value)[:100]
                item["observed_at"] = policy_fact.observed_at
            citations.append(item)
        return {
            "facts": facts,
            "policy_citations": citations,
        }

    def _persist_answer(
        self,
        payload: dict[str, Any],
        tool_trace: list[dict[str, Any]],
        reply: str,
        state: ConsultationState,
        trace_recorder: TraceRecorder | None,
    ) -> dict[str, Any]:
        trusted = list(state.get("trusted_hits") or [])
        knowledge = state.get("knowledge") or {}
        citations = self._citations(trusted)
        append_arguments = {
            "user_id": payload.get("user_id"),
            "session_id": payload.get("session_id"),
            "order_id": payload.get("order_id"),
            "ticket_id": payload.get("ticket_id"),
            "role": "ASSISTANT",
            "content": reply,
            "message_type": "TEXT",
            "knowledge_query": str(payload.get("message") or ""),
            "knowledge_retrieval_mode": knowledge.get("mode"),
            "knowledge_hit_count": len(trusted),
            "knowledge_hits_json": json.dumps(trusted[:5], ensure_ascii=False, default=str),
            "knowledge_trace_json": json.dumps(
                {"citations": citations, "case_facts": state["builder"].build().to_dict()},
                ensure_ascii=False, default=str
            ),
        }
        with self._trace_step(trace_recorder, "java_append_chat_message") as trace_step:
            persisted = self.tools.call("append_chat_message", append_arguments)
            trace_step.details.update(
                {
                    "ok": persisted.ok,
                    "error_category": persisted.error_category,
                }
            )
        tool_trace.append(self._trace_entry(persisted, append_arguments))
        if not persisted.ok:
            return self._handoff(
                payload,
                tool_trace,
                "answer_persistence_failed",
                trace_recorder,
            )
        return self._result(
            reply=reply,
            session_mode="AI",
            need_human=False,
            trace=tool_trace,
            raw={
                "knowledge_mode": knowledge.get("mode"),
                "knowledge_hit_count": len(trusted),
                "policy_citations": citations,
                "answer_sources": self._answer_sources(state),
                "case_facts": state["builder"].build().to_dict(),
                "plan_rounds": int(state.get("plan_round") or 0),
                "tool_calls": int(state.get("tool_call_count") or 0),
                "stop_reason": state.get("stop_reason"),
                "handoff_reason": None,
            },
            payload=payload,
            persistence=persisted.data if isinstance(persisted.data, dict) else None,
        )

    def _request_evidence(
        self,
        payload: dict[str, Any],
        tool_trace: list[dict[str, Any]],
        reply: str,
        evidence_needed: list[str],
        state: ConsultationState,
        trace_recorder: TraceRecorder | None,
    ) -> dict[str, Any]:
        """Ask the user for one concrete credential before the ticket is filed."""
        arguments = {
            "user_id": payload.get("user_id"),
            "session_id": payload.get("session_id"),
            "order_id": payload.get("order_id"),
            "ticket_id": payload.get("ticket_id"),
            "assistant_reply": reply,
            "evidence_needed": evidence_needed,
        }
        with self._trace_step(
            trace_recorder,
            "java_request_missing_evidence",
            evidence_count=len(evidence_needed),
        ) as trace_step:
            result = self.tools.call("request_missing_evidence", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        tool_trace.append(self._trace_entry(result, arguments))
        if not result.ok:
            return self._handoff(
                payload,
                tool_trace,
                "evidence_request_failed",
                trace_recorder,
            )
        return self._result(
            reply=reply,
            session_mode="AI",
            need_human=False,
            trace=tool_trace,
            raw={
                "knowledge_mode": (state.get("knowledge") or {}).get("mode"),
                "knowledge_hit_count": len(state.get("trusted_hits") or []),
                "policy_citations": self._citations(list(state.get("trusted_hits") or [])),
                "answer_sources": self._answer_sources(state),
                "case_facts": state["builder"].build().to_dict(),
                "evidence_needed": evidence_needed,
                "stop_reason": "evidence_requested",
                "handoff_reason": None,
            },
            payload=payload,
            persistence=result.data if isinstance(result.data, dict) else None,
            evidence_needed=evidence_needed,
        )

    def _handoff(
        self,
        payload: dict[str, Any],
        trace: list[dict[str, Any]],
        reason: str,
        trace_recorder: TraceRecorder | None,
        case_context: CaseContext | None = None,
    ) -> dict[str, Any]:
        reply = "当前知识库无法可靠回答该问题，已为您转接人工客服继续核对。"
        conflicts = (
            [item.describe() for item in (*case_context.conflicts, *case_context.discrepancies)][:2]
            if case_context else []
        )
        if conflicts:
            reply = f"核验信息存在冲突：{'；'.join(conflicts)}。已转人工客服继续核对。"
        summary = "\n".join(
            (
                f"用户诉求：{str(payload.get('message') or '售后问题核对').strip()}",
                "已核实：自动知识检索未形成可直接回答的可信结论。",
                "待核实：适用政策、订单事实及后续处理方案。",
                f"转人工原因：{reason}",
                *(f"事实冲突：{item}" for item in conflicts),
                "建议下一步：人工客服结合订单和有效政策继续核对。",
            )
        )
        arguments = {
            "user_id": payload.get("user_id"),
            "session_id": payload.get("session_id"),
            "order_id": payload.get("order_id"),
            "ticket_id": payload.get("ticket_id"),
            "summary": summary,
        }
        with self._trace_step(
            trace_recorder,
            "java_handoff_to_human",
            reason=reason,
        ) as trace_step:
            result = self.tools.call("handoff_to_human", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        trace.append(self._trace_entry(result, arguments))
        confirmed = bool(
            result.ok
            and isinstance(result.data, dict)
            and str(result.data.get("mode") or "").upper() == "HUMAN"
        )
        if not confirmed:
            reply = (
                f"核验信息存在冲突：{'；'.join(conflicts)}。人工转接暂未确认成功，请稍后重试。"
                if conflicts else "当前问题需要人工进一步核对，但人工转接暂未确认成功，请稍后重试。"
            )
        return self._result(
            reply=reply,
            session_mode="HUMAN" if confirmed else "AI",
            need_human=True,
            trace=trace,
            raw={
                "knowledge_mode": None,
                "knowledge_hit_count": 0,
                "policy_citations": [],
                "handoff_reason": reason,
                "stop_reason": reason,
                "handoff_succeeded": confirmed,
                "case_conflicts": conflicts,
            },
            payload=payload,
            persistence=result.data if isinstance(result.data, dict) else None,
        )

    # ------------------------------------------------------------------
    # 检索改写：由工作流驱动，不占用模型的规划预算
    # ------------------------------------------------------------------

    def _rewrite_and_retrieve(
        self,
        state: ConsultationState,
        knowledge: dict[str, Any],
        previous_queries: list[str],
        trace_recorder: TraceRecorder | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        if self.rag_rewrite_service is None:
            return knowledge, [], []
        payload = state["payload"]
        client_context = (
            payload.get("client_context")
            if isinstance(payload.get("client_context"), dict)
            else {}
        )
        order = (
            client_context.get("selected_order_hint")
            if isinstance(client_context.get("selected_order_hint"), dict)
            else {}
        )
        original_query = str(payload.get("message") or "")
        try:
            with self._trace_step(
                trace_recorder,
                "rag_query_rewrite",
                previous_query_count=len(previous_queries),
            ) as trace_step:
                decision = self.rag_rewrite_service.evaluate(
                    user_question=original_query,
                    task="回答售后政策咨询；知识不足时转人工，不作业务审核决定。",
                    known_facts={
                        "product_name": order.get("product_name"),
                        "product_category": (
                            order.get("category") or order.get("product_category")
                        ),
                        "after_sales_type": order.get("after_sales_type"),
                    },
                    original_query=original_query,
                    previous_queries=list(previous_queries),
                    require_trusted_policy=True,
                    retrieval_result=knowledge,
                    allow_rewrite=True,
                )
                trace_step.details.update(
                    {
                        "sufficient": bool(decision.sufficient),
                        "candidate_count": len(decision.queries),
                    }
                )
        except RagRewriteError:
            return knowledge, [], []
        queries = [
            str(item.query)
            for item in getattr(decision, "queries", ())
            if str(getattr(item, "query", "")).strip()
        ]
        if not queries:
            return knowledge, [], []
        multi_arguments = {
            "user_id": payload.get("user_id"),
            "original_query": original_query,
            "queries": queries[:3],
            **self._trusted_retrieval_filters(state),
        }
        with self._trace_step(
            trace_recorder,
            "rag_retrieve_multi",
            query_count=len(queries[:3]),
        ) as trace_step:
            result = self.tools.call("retrieve_knowledge_multi", multi_arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        tool_trace = [{
            **self._trace_entry(result, multi_arguments),
            "reason": "初次检索未取得可信政策，按相同业务过滤条件补充查询",
        }]
        rewritten = result.data if result.ok and isinstance(result.data, dict) else knowledge
        trusted = trusted_policy_hits(rewritten)
        return rewritten, trusted, tool_trace

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _system_prompt(self, round_no: int = 1) -> str:
        return planner_system_prompt(round_no)

    @staticmethod
    def _observation(call_id: str, name: str, content: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps(content, ensure_ascii=False, default=str),
        }

    @staticmethod
    def _observation_payload(result: ToolResult) -> dict[str, Any]:
        return ContextProjector().project(result)

    @staticmethod
    def _citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for hit in hits:
            for item in hit.get("citations") or []:
                if (
                    isinstance(item, dict)
                    and str(item.get("source_code") or "").strip()
                    and str(item.get("chunk_id") or item.get("document_id") or "").strip()
                ):
                    normalized = dict(item)
                    if normalized not in citations:
                        citations.append(normalized)
        return citations

    @staticmethod
    def _explicit_human_request(payload: dict[str, Any]) -> bool:
        """Whether the user asked for a human in this turn or a recent one."""
        return is_explicit_human_request(
            str(payload.get("message") or ""),
            list(payload.get("recent_history") or []),
        )

    @staticmethod
    def _trace_entry(
        result: ToolResult,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return ContextProjector().public_trace(result)

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

    @staticmethod
    def _result(
        *,
        reply: str,
        session_mode: str,
        need_human: bool,
        trace: list[dict[str, Any]],
        raw: dict[str, Any],
        payload: dict[str, Any],
        persistence: dict[str, Any] | None = None,
        evidence_needed: list[str] | None = None,
    ) -> dict[str, Any]:
        persisted = persistence or {}
        session_id = persisted.get("session_id") or persisted.get("sessionId")
        return {
            "assistant_reply": reply,
            "session_mode": session_mode,
            "tool_trace": trace,
            "ticket": None,
            "review_result": None,
            "need_human": need_human,
            "evidence_needed": list(evidence_needed or []),
            "persistence": {
                "session_id": (
                    str(session_id)
                    if session_id is not None
                    else str(payload.get("session_id") or "") or None
                ),
                "ticket_no": None,
            },
            "raw": {"runtime": "agentic_rag_chat", **raw},
        }


def _first_order_id(data: Any) -> str:
    rows = data if isinstance(data, list) else [data]
    identifiers = {
        str(row["order_id"]) for row in rows
        if isinstance(row, dict) and row.get("order_id")
    }
    return next(iter(identifiers)) if len(identifiers) == 1 else ""


def _first_ticket_id(data: Any) -> str:
    if isinstance(data, dict) and data.get("ticket_id"):
        return str(data["ticket_id"])
    return ""
