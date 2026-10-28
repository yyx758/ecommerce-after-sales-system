"""确定性安全护栏：运行时与离线评测共用同一份实现。

这些护栏过去散落在一个从不在线上运行的类里，评测脚本只能静态调用它们，
于是"被评测的逻辑"和"实际跑的逻辑"其实是两份。现在它们集中在这里，
审核链路、会话链路和离线评测引用的是同一处代码。
"""

from __future__ import annotations

from typing import Any

#: 用户明确要求人工服务的关键词。
HUMAN_REQUEST_KEYWORDS: tuple[str, ...] = (
    "转人工",
    "人工客服",
    "真人客服",
    "人工帮助",
    "联系客服",
    "转接人工",
)


def is_explicit_human_request(
    message: str,
    recent_history: list[dict[str, Any]] | None = None,
) -> bool:
    """Whether the user asked for a human, now or in the recent history.

    The history check matters: a user who asked for a human two turns ago and
    then asked a follow-up question still wants a human.
    """
    text = str(message or "")
    if any(keyword in text for keyword in HUMAN_REQUEST_KEYWORDS):
        return True
    for item in reversed(recent_history or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").upper() != "USER":
            continue
        content = str(item.get("content") or "")
        if any(keyword in content for keyword in HUMAN_REQUEST_KEYWORDS):
            return True
    return False


def allow_ai_review_submit(payload: dict[str, Any]) -> bool:
    """Whether this payload may submit an AI review verdict.

    Only the trusted Kafka review path may drive a verdict. A chat request
    that forges ``client_context.source`` is rewritten by the payload adapter
    before it reaches here.
    """
    client_context = (
        payload.get("client_context")
        if isinstance(payload.get("client_context"), dict)
        else {}
    )
    return str(client_context.get("source") or "").strip().lower() == "kafka"


def policy_hit_score(hit: dict[str, Any]) -> float:
    """The ranking score of one retrieval hit."""
    for key in ("calibrated_policy_confidence", "rerank_score", "score"):
        value = hit.get(key)
        if value is None:
            continue
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            continue
    return 0.0


def best_policy_score(hits: list[dict[str, Any]]) -> float:
    """The best ranking score among the given hits."""
    return round(max((policy_hit_score(hit) for hit in hits), default=0.0), 4)
