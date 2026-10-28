"""Select sourced case context for one bounded ReAct planning call."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import threading
from typing import Any

from ...facts import CaseContext
from .context_diff import ContextDiff


class ContextBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class ContextView:
    current_message: str
    current_goal: dict[str, Any]
    selected_scope: dict[str, str]
    request_hints: dict[str, str]
    recent_turns: list[dict[str, str]]
    history_background: dict[str, Any]
    facts: list[dict[str, Any]]
    policy_excerpts: list[dict[str, Any]]
    evidence_state: dict[str, Any]
    open_questions: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    unknowns: list[str]
    context_diff: dict[str, Any]
    omission_reasons: list[str]

    def model_payload(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items()
                if key not in {"omission_reasons", "context_diff"}}


class ContextAssembler:
    """No model call or business verdict; fail closed if mandatory context cannot fit."""

    def __init__(self, *, model_limit: int | None = None, output_reserve: int = 900,
                 safety_reserve: int | None = None) -> None:
        self.model_limit = model_limit or int(os.getenv("AGENT_CONTEXT_WINDOW_TOKENS", "8192"))
        self.output_reserve = output_reserve
        self.safety_reserve = safety_reserve or int(os.getenv("AGENT_CONTEXT_SAFETY_TOKENS", "2048"))
        if self.model_limit <= self.output_reserve + self.safety_reserve:
            raise ValueError("context window must exceed output and safety reserves")
        self._calibration_factor = 1.0
        self._calibration_lock = threading.Lock()

    @property
    def input_budget(self) -> int:
        return self.model_limit - self.output_reserve - self.safety_reserve

    @staticmethod
    def estimate(value: Any) -> int:
        # Conservative for Chinese prose, JSON punctuation, and provider framing.
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        return len(serialized.encode("utf-8")) // 3 + 1

    def view(self, payload: dict[str, Any], context: CaseContext, *, round_no: int,
             seen_fact_keys: set[tuple[str, str, str, str]] | None = None,
             resolved_order_id: str = "", resolved_ticket_id: str = "") -> ContextView:
        summary = payload.get("history_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        goal = summary.get("current_user_goal")
        if isinstance(goal, str):
            goal = {"text": goal, "trust": "claimed", "status": summary.get("current_goal_status") or "unknown",
                    "source_message_id": summary.get("current_user_goal_message_id")}
        if not isinstance(goal, dict):
            goal = {}
        if not goal.get("text"):
            goal = {"text": str(payload.get("message") or ""), "trust": "claimed",
                    "status": "unknown", "source_message_id": summary.get("current_message_id")}
        goal = {**goal, "relation_to_current_message": summary.get("goal_relation") or "UNCERTAIN"}
        facts = []
        policy = []
        always_keep = {"order.status", "ticket.status", "ticket.policy_version", "ticket.evidence_revision"}
        for fact in context.facts:
            identity = (fact.claim_key, fact.source_ref, repr(fact.value), fact.context_version)
            if (round_no > 1 and seen_fact_keys is not None and identity in seen_fact_keys
                    and fact.claim_key not in always_keep
                    and not fact.claim_key.startswith(("policy.evidence.", "visual."))):
                continue
            item = {key: value for key, value in fact.to_dict().items()
                    if value is not None and value != "" and value is not False}
            if fact.source_kind == "policy" and fact.claim_key.startswith("policy.evidence."):
                policy.append(item)
            elif fact.claim_key != "user.statement":
                facts.append(item)
        recent = []
        if round_no == 1:
            for item in list(payload.get("recent_history") or [])[-4:]:
                if isinstance(item, dict) and item.get("role") in {"user", "assistant"}:
                    recent.append({key: str(item[key]) for key in ("role", "content", "message_id") if item.get(key)})
        open_questions = summary.get("open_questions") or []
        if not isinstance(open_questions, list):
            open_questions = []
        return ContextView(
            current_message=str(payload.get("message") or ""), current_goal=goal,
            selected_scope={"order_id": resolved_order_id, "ticket_id": resolved_ticket_id},
            request_hints={"order_id": str(payload.get("order_id") or "") if not resolved_order_id else "",
                           "ticket_id": str(payload.get("ticket_id") or "") if not resolved_ticket_id else ""},
            recent_turns=recent, facts=facts, policy_excerpts=policy,
            history_background={"text": str(summary.get("conversation_summary") or "")[:300],
                                "trust": "claimed", "source": "mysql_history",
                                "through_message_id": summary.get("summary_through_message_id")}
            if round_no == 1 else {},
            evidence_state={"attachment_count": len(payload.get("attachments") or []),
                            "evidence_refs": summary.get("evidence_refs") or []},
            open_questions=open_questions, conflicts=[item.to_dict() for item in context.conflicts]
            + [item.to_dict() for item in context.discrepancies],
            unknowns=list(context.unknowns),
            context_diff=vars(ContextDiff.build(payload, context)),
            omission_reasons=[],
        )

    def prepare(self, *, system_prompt: str, tool_schemas: list[dict[str, Any]],
                messages: list[dict[str, Any]], view: ContextView,
                metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], int, list[str]]:
        body = {**view.model_payload(), **metadata}
        omissions: list[str] = []

        def rendered() -> list[dict[str, Any]]:
            return [*messages, {"role": "user", "content": json.dumps(body, ensure_ascii=False, default=str)}]

        def size() -> int:
            base = self.estimate({"system": system_prompt, "tools": tool_schemas, "messages": rendered()})
            with self._calibration_lock:
                return int(base * self._calibration_factor)

        while size() > self.input_budget and body["recent_turns"]:
            body["recent_turns"].pop(0)
            omissions.append("old_recent_turn")
        if size() > self.input_budget and body["history_background"]:
            body["history_background"] = {}
            omissions.append("old_history_background")
        while size() > self.input_budget and len(body["facts"]) > 0:
            removable = next((index for index, fact in enumerate(body["facts"])
                              if fact.get("claim_key") not in {"order.status", "ticket.status",
                                                               "ticket.policy_version", "ticket.evidence_revision"}), None)
            if removable is None:
                break
            body["facts"].pop(removable)
            omissions.append("noncritical_fact")
        if size() > self.input_budget and messages and messages[0].get("role") == "user":
            exchange_end = 1
            if len(messages) > 1 and messages[1].get("role") == "assistant":
                calls = messages[1].get("tool_calls") or []
                if calls:
                    ids = {str(call.get("id")) for call in calls}
                    tool_names = {str((call.get("function") or {}).get("name")) for call in calls}
                    cursor = 2
                    while cursor < len(messages) and messages[cursor].get("role") == "tool":
                        cursor += 1
                    returned = {str(item.get("tool_call_id")) for item in messages[2:cursor]}
                    can_replace = tool_names == {"retrieve_knowledge"}
                    sources_present = bool(body["policy_excerpts"])
                    if ids <= returned and can_replace and sources_present:
                        exchange_end = cursor
                    else:
                        exchange_end = 0
            if exchange_end > 1:
                del messages[:exchange_end]
                omissions.append("completed_tool_exchange")
        if size() > self.input_budget:
            raise ContextBudgetExceeded("mandatory_context_exceeds_budget")
        return rendered(), size(), omissions

    def calibrate(self, estimated: int, actual_input_tokens: int) -> None:
        if estimated <= 0 or actual_input_tokens <= estimated:
            return
        with self._calibration_lock:
            self._calibration_factor = min(2.0, max(
                self._calibration_factor,
                self._calibration_factor * actual_input_tokens / estimated,
            ))
