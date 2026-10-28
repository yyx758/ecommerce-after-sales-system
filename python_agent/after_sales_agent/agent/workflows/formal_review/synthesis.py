from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Protocol

from .contracts import (
    ReviewAssessment,
    ReviewProposal,
    TrustedCaseContext,
)


class JsonLlm(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...


_SYNTHESIZE_SCHEMA = {
    "type": "object",
    "required": [
        "proposed_verdict",
        "reason",
        "confidence",
        "risk_reasons",
        "assistant_reply",
    ],
    "properties": {
        "proposed_verdict": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
        "risk_reasons": {"type": "array", "items": {"type": "string"}},
        "assistant_reply": {"type": "string"},
    },
}


@dataclass
class ComplexReviewSynthesizer:
    """仅综合复杂案例，不负责工作流调度或最终业务决策。"""

    llm: JsonLlm

    def synthesize(
        self,
        context: TrustedCaseContext,
        issue: str,
        review: ReviewAssessment,
    ) -> ReviewProposal:
        system_prompt = (
                "你是正式售后审核工作流内的复杂案例综合节点。"
                "只综合单份审核评估，提出 APPROVE 或 "
                "MANUAL_REVIEW_REQUIRED 建议。不得执行工具、修改业务状态或绕过"
                "确定性 Gate。只输出 JSON：proposed_verdict、reason、confidence、"
                "risk_reasons、assistant_reply。不得添加输入中不存在的事实。"
            )
        user_prompt = json.dumps(
                {
                    "issue": issue,
                    "trusted_context": {
                        "ticket_status": context.ticket_status,
                        "policy_version": context.policy_version,
                        "context_version": context.context_version,
                    },
                    "review_assessment": review.to_dict(),
                },
                ensure_ascii=False,
                default=str,
            )
        model_limit = int(os.getenv("AGENT_CONTEXT_WINDOW_TOKENS", "8192"))
        safety_reserve = int(os.getenv("AGENT_CONTEXT_SAFETY_TOKENS", "2048"))
        estimated_input = len(json.dumps({"system": system_prompt, "user": user_prompt,
                                          "schema": _SYNTHESIZE_SCHEMA}, ensure_ascii=False).encode("utf-8")) // 3 + 1
        if estimated_input > model_limit - 500 - safety_reserve:
            return ReviewProposal(
                proposed_verdict="MANUAL_REVIEW_REQUIRED",
                reason="context_budget_exhausted：必要审核依据超出模型输入预算，转人工复核。",
                confidence=0.0,
                risk_reasons=("context_budget_exhausted",),
                assistant_reply="您的售后申请需要人工复核，具体结果以系统审核状态为准。",
                model_confidence=0.0,
            )
        raw = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=_SYNTHESIZE_SCHEMA,
            temperature=0.1,
            max_tokens=500,
        )
        verdict = str(raw.get("proposed_verdict") or "").strip().upper()
        if verdict not in {"APPROVE", "MANUAL_REVIEW_REQUIRED"}:
            verdict = "MANUAL_REVIEW_REQUIRED"
        try:
            confidence = max(
                0.0,
                min(float(raw.get("confidence") or 0.0), 1.0),
            )
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            reason = "工作流结果存在不确定性，建议人工复核。"
        reply = str(raw.get("assistant_reply") or "").strip()
        if not reply:
            reply = "您的售后申请已完成智能初审，实际结果以系统审核状态为准。"
        return ReviewProposal(
            proposed_verdict=verdict,
            reason=reason[:500],
            confidence=0.0,
            risk_reasons=tuple(
                str(item)
                for item in raw.get("risk_reasons") or []
                if str(item or "").strip()
            ),
            assistant_reply=reply[:500],
            model_confidence=confidence,
        )
