"""把工具结果翻译成带来源的事实记录。

每个抽取函数只负责"从一种工具结果里读出哪些结论、这些结论来自哪个来源"，
不做业务判断，也不做信任判定之外的过滤。可信等级由调用方按来源性质指定：

* 订单 / 工单 / 商家政策 → ``VERIFIED``（Java 侧做过归属校验，是权威来源）
* 政策检索命中 → ``REPORTED``（仍要过可信过滤才能升到这一级）
* 凭证图片 → ``REPORTED``（模型看图结论，可复述但不可当权威）
"""

from __future__ import annotations

import hashlib
from typing import Any

from .models import CaseFact, SourceKind, TrustLevel, utc_now_iso

#: 政策检索的命中模式白名单：只有这几种模式产出的结果才可能携带可信政策。
TRUSTED_RETRIEVAL_MODES = frozenset(
    {"hybrid_reranked", "pgvector", "multi_query_reranked", "multi_query_rrf"}
)


def citations_of(hit: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the traceable citations of one retrieval hit."""
    raw = hit.get("citations")
    if not isinstance(raw, list):
        single = hit.get("citation")
        raw = [single] if isinstance(single, dict) else []
    citations: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_code = str(item.get("source_code") or "").strip()
        trace = str(item.get("chunk_id") or item.get("document_id") or "").strip()
        if not (source_code and trace):
            continue
        if item not in citations:
            citations.append(dict(item))
    return citations


def trusted_policy_hits(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the hits that passed every policy trust filter.

    The filter is deliberately code-owned: the model may not promote a hit to
    "trusted" on its own authority.
    """
    if not isinstance(knowledge, dict):
        return []
    if knowledge.get("trusted_policy_eligible") is not True:
        return []
    if str(knowledge.get("filter_level") or "") != "strict":
        return []
    if (
        knowledge.get("reranker_succeeded") is not True
        and str(knowledge.get("mode") or "") != "multi_query_rrf"
    ):
        return []
    if str(knowledge.get("mode") or "") not in TRUSTED_RETRIEVAL_MODES:
        return []
    trusted: list[dict[str, Any]] = []
    for hit in knowledge.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        if str(hit.get("source_type") or "") != "after_sales_policy":
            continue
        if hit.get("trusted_policy_eligible") is not True:
            continue
        if str(hit.get("relaxation_level") or "") != "strict":
            continue
        if not citations_of(hit):
            continue
        trusted.append(dict(hit))
    return trusted


def _string(value: Any) -> str:
    return str(value or "").strip()


def evidence_fingerprint(source: Any) -> str:
    return hashlib.sha256(_string(source).encode("utf-8")).hexdigest()[:16]


def order_facts(data: Any) -> list[CaseFact]:
    """Facts from an order summary (single object or list of them)."""
    rows = data if isinstance(data, list) else [data]
    facts: list[CaseFact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        order_id = _string(row.get("order_id"))
        order_no = _string(row.get("order_no"))
        source_ref = order_no or order_id or "order"
        observed = utc_now_iso()
        fields = (
            ("order.id", order_id),
            ("order.no", order_no),
            ("order.status", _string(row.get("status"))),
            ("order.product_name", _string(row.get("product_name"))),
            ("order.category", _string(row.get("category"))),
            ("order.amount", row.get("amount")),
            ("order.merchant_code", _string(row.get("merchant_code"))),
            ("order.created_at", _string(row.get("create_time"))),
            ("order.existing_ticket_id", _string(row.get("existing_ticket_id"))),
            ("order.existing_ticket_status", _string(row.get("existing_ticket_status"))),
        )
        for claim_key, value in fields:
            if value in (None, ""):
                continue
            facts.append(
                CaseFact(
                    claim_key=claim_key,
                    value=value,
                    trust=TrustLevel.VERIFIED,
                    source_kind=SourceKind.ORDER,
                    source_ref=source_ref,
                    observed_at=observed,
                )
            )
    return facts


def ticket_facts(data: Any) -> list[CaseFact]:
    """Facts from an after-sales ticket."""
    if not isinstance(data, dict) or not data:
        return []
    ticket_id = _string(data.get("ticket_id"))
    ticket_no = _string(data.get("ticket_no"))
    source_ref = ticket_no or ticket_id or "ticket"
    observed = utc_now_iso()
    fields = (
        ("ticket.id", ticket_id),
        ("ticket.no", ticket_no),
        ("ticket.order_id", _string(data.get("order_id"))),
        ("ticket.merchant_code", _string(data.get("merchant_code"))),
        ("ticket.category", _string(data.get("category"))),
        ("ticket.status", _string(data.get("status"))),
        ("ticket.after_sales_type", _string(data.get("after_sales_type"))),
        ("ticket.reason", _string(data.get("reason"))),
        ("ticket.reason_detail", _string(data.get("reason_detail"))),
        ("ticket.description", _string(data.get("description"))),
        ("ticket.refund_amount", data.get("refund_amount")),
        ("ticket.policy_version", _string(data.get("policy_version"))),
        ("ticket.applied_at", _string(data.get("after_sales_applied_at"))),
        ("ticket.evidence_revision", data.get("evidence_revision")),
        ("ticket.evidence_refs", tuple(dict.fromkeys(
            evidence_fingerprint(url) for url in data.get("evidence_urls") or [] if _string(url)
        ))),
        ("ticket.ai_review_status", _string(data.get("ai_review_status"))),
        ("ticket.ai_review_result", _string(data.get("ai_review_result"))),
    )
    facts: list[CaseFact] = []
    for claim_key, value in fields:
        if value in (None, ""):
            continue
        facts.append(
            CaseFact(
                claim_key=claim_key,
                value=value,
                trust=TrustLevel.VERIFIED,
                source_kind=SourceKind.TICKET,
                source_ref=source_ref,
                observed_at=observed,
                    context_version=_string(data.get("context_version")),
                    evidence_revision=data.get("evidence_revision"),
            )
        )
    return facts


def merchant_policy_facts(data: Any) -> list[CaseFact]:
    """Facts from the merchant policy configuration."""
    if not isinstance(data, dict) or not data:
        return []
    merchant_code = _string(data.get("merchant_code")) or "merchant"
    observed = utc_now_iso()
    facts: list[CaseFact] = []
    for key, value in data.items():
        name = _string(key)
        if not name or name == "merchant_code":
            continue
        if isinstance(value, (dict, list)):
            continue
        facts.append(
            CaseFact(
                claim_key=f"merchant_policy.{name}",
                value=value,
                trust=TrustLevel.VERIFIED,
                source_kind=SourceKind.MERCHANT_POLICY,
                source_ref=merchant_code,
                observed_at=observed,
            )
        )
    return facts


def policy_facts(knowledge: dict[str, Any]) -> list[CaseFact]:
    """Facts from a knowledge retrieval result.

    Only hits that already passed :func:`trusted_policy_hits` become facts;
    an untrusted retrieval contributes no policy claim at all.
    """
    if not isinstance(knowledge, dict):
        return []
    hits = trusted_policy_hits(knowledge)
    mode = _string(knowledge.get("mode"))
    observed = utc_now_iso()
    facts: list[CaseFact] = []
    citations: list[dict[str, Any]] = []
    required: list[str] = []
    for hit in hits:
        hit_citations = citations_of(hit)
        for citation in hit_citations:
            if citation not in citations:
                citations.append(citation)
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        for item in metadata.get("default_evidence") or []:
            text = _string(item)
            if text and text not in required:
                required.append(text)
        source_code = ""
        chunk_id = ""
        if hit_citations:
            source_code = _string(hit_citations[0].get("source_code"))
            chunk_id = _string(
                hit_citations[0].get("chunk_id") or hit_citations[0].get("document_id")
            )
        source_ref = f"{source_code}@{chunk_id}" if source_code and chunk_id else "policy"
        facts.append(
            CaseFact(
                claim_key=f"policy.evidence.{source_ref}",
                value=_string(hit.get("snippet"))[:500],
                trust=TrustLevel.REPORTED,
                source_kind=SourceKind.POLICY,
                source_ref=source_ref,
                observed_at=observed,
                detail=_string(hit.get("policy_version")),
                comparable=False,
            )
        )
    facts.append(
        CaseFact(
            claim_key="policy.retrieval_mode",
            value=mode,
            trust=TrustLevel.REPORTED,
            source_kind=SourceKind.POLICY,
            source_ref="retriever",
            observed_at=observed,
            comparable=False,
        )
    )
    facts.append(
        CaseFact(
            claim_key="policy.citations",
            value=[_string(item.get("source_code")) for item in citations],
            trust=TrustLevel.REPORTED,
            source_kind=SourceKind.POLICY,
            source_ref="retriever",
            observed_at=observed,
            comparable=False,
        )
    )
    if required:
        facts.append(
            CaseFact(
                claim_key="policy.evidence_required",
                value=tuple(required),
                trust=TrustLevel.REPORTED,
                source_kind=SourceKind.POLICY,
                source_ref="retriever",
                observed_at=observed,
                comparable=False,
            )
        )
    return facts


def visual_facts(data: Any) -> list[CaseFact]:
    """Facts from a credential image review."""
    if not isinstance(data, dict) or data.get("success") is not True:
        return []
    observed = utc_now_iso()
    source_ref = "image_review"
    fields = (
        ("visual.evidence_consistent", data.get("evidence_consistent")),
        ("visual.confidence", data.get("confidence")),
        ("visual.tampering_suspected", data.get("tampering_suspected")),
        ("visual.issue_types", tuple(data.get("observed_issue_types") or ())),
        ("visual.missing_evidence", tuple(data.get("missing_visual_evidence") or ())),
        ("visual.verification_limitations", tuple(data.get("verification_limitations") or ())),
    )
    facts: list[CaseFact] = []
    for claim_key, value in fields:
        if value in (None, "", (), []):
            continue
        facts.append(
            CaseFact(
                claim_key=claim_key,
                value=value,
                trust=TrustLevel.REPORTED,
                source_kind=SourceKind.IMAGE,
                source_ref=source_ref,
                observed_at=observed,
                comparable=False,
            )
        )
    return facts


def user_claim_facts(message: str, source_ref: str = "user") -> list[CaseFact]:
    """The user's own statement, recorded at the lowest trust level."""
    text = _string(message)
    if not text:
        return []
    return [
        CaseFact(
            claim_key="user.statement",
            value=text,
            trust=TrustLevel.CLAIMED,
            source_kind=SourceKind.USER,
            source_ref=source_ref,
            comparable=False,
        )
    ]


#: Tool name → fact extractor.
_EXTRACTORS = {
    "search_user_orders": order_facts,
    "get_order_detail": order_facts,
    "get_existing_after_sales": ticket_facts,
    "get_after_sales_ticket": ticket_facts,
    "get_merchant_policy": merchant_policy_facts,
    "retrieve_knowledge": policy_facts,
    "review_images": visual_facts,
}


def facts_from_tool(tool_name: str, data: Any) -> list[CaseFact]:
    """Extract the facts carried by one tool result."""
    extractor = _EXTRACTORS.get(tool_name)
    if extractor is None:
        return []
    try:
        return extractor(data)
    except Exception:  # noqa: BLE001 - a broken payload must not break the turn
        return []
