from __future__ import annotations

from datetime import datetime
from typing import Any

from .contracts import ReviewAssessment, TrustedCaseContext
from ....tools import ToolResult


def _score(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def is_core_evidence_requirement(value: Any) -> bool:
    text = str(value or '').strip()
    if not text or any(word in text for word in ('外包装', '物流', '面单', '运单', '快递')):
        return False
    return any(word in text for word in ('商品', '问题', '破损', '损坏')) and any(
        word in text for word in ('图片', '照片')
    )


def _parse_time(value: Any) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    normalized = f'{text[:-1]}+00:00' if text.endswith(('Z', 'z')) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _citations(hit: dict[str, Any]) -> list[dict[str, Any]]:
    value = hit.get('citations')
    if not isinstance(value, list):
        value = [hit.get('citation')]
    return [
        dict(item) for item in value
        if isinstance(item, dict)
        and str(item.get('source_code') or '').strip()
        and str(item.get('chunk_id') or item.get('document_id') or '').strip()
    ]


def trusted_policy_hits(
    context: TrustedCaseContext,
    knowledge: dict[str, Any],
) -> list[dict[str, Any]]:
    """The hits that are strong enough to authorize an automatic decision.

    Every condition is traceable: source type, merchant, policy version, the
    validity window at the business time, the hit threshold and a citation that
    points back to a chunk.
    """
    mode = str(knowledge.get('mode') or '')
    business_time = _parse_time(context.business_time)
    trusted_hits: list[dict[str, Any]] = []
    for hit in knowledge.get('hits') or []:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
        if str(hit.get('source_type') or metadata.get('source_type') or '') != 'after_sales_policy':
            continue
        if not context.merchant_code or str(hit.get('merchant_code') or metadata.get('merchant_code') or '') != context.merchant_code:
            continue
        if not context.policy_version or str(hit.get('policy_version') or metadata.get('policy_version') or '') != context.policy_version:
            continue
        if hit.get('trusted_policy_eligible') is not True or hit.get('relaxation_level') != 'strict':
            continue
        if not _citations(hit):
            continue
        valid_from = _parse_time(hit.get('valid_from') or metadata.get('valid_from'))
        valid_to = _parse_time(hit.get('valid_to') or metadata.get('valid_to'))
        if business_time is not None and valid_from is not None and valid_to is not None:
            if not valid_from <= business_time < valid_to:
                continue
        threshold = _score(hit.get('threshold') or knowledge.get('threshold') or 0.55)
        if mode != 'multi_query_rrf':
            score = _score(hit.get('calibrated_policy_confidence', hit.get('rerank_score')))
            if score < threshold:
                continue
        trusted_hits.append(hit)
    return trusted_hits


def policy_facts(context: TrustedCaseContext, result: ToolResult) -> dict[str, Any]:
    facts: dict[str, Any] = {
        'policy_success': False,
        'trusted_policy_eligible': False,
        'policy_version_matched': False,
        'filter_level': None,
        'reranker_succeeded': False,
        'retrieval_mode': None,
        'policy_match_score': 0.0,
        'policy_threshold': 0.55,
        'required_evidence': (),
        'citations': (),
        'policy_issues': (result.error_category or 'policy_tool_failed',),
    }
    if not result.ok or not isinstance(result.data, dict):
        return facts

    knowledge = result.data
    mode = str(knowledge.get('mode') or '')
    trusted_hits = trusted_policy_hits(context, knowledge)

    required: list[str] = []
    citations: list[dict[str, Any]] = []
    for hit in trusted_hits:
        metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
        for item in metadata.get('default_evidence') or []:
            text = str(item or '').strip()
            if text and text not in required:
                required.append(text)
        for citation in _citations(hit):
            if citation not in citations:
                citations.append(citation)
    filter_level = str(knowledge.get('filter_level') or knowledge.get('relaxation_level') or '') or None
    eligible = bool(
        trusted_hits
        and knowledge.get('trusted_policy_eligible') is True
        and filter_level == 'strict'
        and mode in {'hybrid_reranked', 'multi_query_reranked', 'multi_query_rrf', 'pgvector'}
    )
    facts.update(
        policy_success=True,
        trusted_policy_eligible=eligible,
        policy_version_matched=bool(trusted_hits),
        filter_level=filter_level,
        reranker_succeeded=knowledge.get('reranker_succeeded') is True,
        retrieval_mode=mode or None,
        policy_match_score=(
            1.0 if mode == 'multi_query_rrf' and trusted_hits
            else max((_score(hit.get('rerank_score')) for hit in trusted_hits), default=0.0)
        ),
        policy_threshold=_score(knowledge.get('threshold') or 0.55),
        required_evidence=tuple(required),
        citations=tuple(citations),
        policy_issues=() if eligible else ('policy_not_strictly_trusted',),
    )
    return facts


def visual_facts(result: ToolResult) -> dict[str, Any]:
    facts: dict[str, Any] = {
        'visual_success': False,
        'visual_verifiable': False,
        'evidence_consistent': None,
        'visual_confidence': 0.0,
        'satisfied_evidence': (),
        'missing_evidence': (),
        'risk_signals': (),
        'visual_issues': (result.error_category or 'vision_tool_failed',),
        'image_review': None,
        'evidence_categories': (),
        'observed_issue_types': (),
        'verification_limitations': (),
    }
    if not result.ok or not isinstance(result.data, dict):
        return facts
    review = result.data
    if review.get('success') is not True:
        return facts
    items = [item for item in review.get('items') or [] if isinstance(item, dict)]
    confidence = min((_score(item.get('confidence')) for item in items), default=_score(review.get('confidence')))
    has_visible_problem = bool(
        review.get('has_damage_area') or review.get('has_visible_issue')
        or any(item.get('issue_visible') is True or item.get('contains_damage_area') is True for item in items)
    )
    item_relevant = any(
        item.get('issue_visible') is True or item.get('contains_damage_area') is True
        for item in items
        if item.get('contains_damage_area') is True or _score(item.get('evidence_relevance')) >= 0.6
    )
    relevant = bool(review.get('has_damage_area') or review.get('evidence_relevant') or item_relevant)
    tampering = bool(review.get('tampering_suspected') or any(item.get('tampering_suspected') is True for item in items))
    contradictory = any(str(item.get('evidence_consistency') or '').lower() == 'contradictory' for item in items)
    if review.get('evidence_consistent') is False or tampering or contradictory:
        consistent: bool | None = False
    elif review.get('evidence_consistent') is True or (has_visible_problem and relevant):
        consistent = True
    else:
        consistent = None
    missing = tuple(dict.fromkeys(
        str(item) for item in review.get('missing_visual_evidence') or []
        if is_core_evidence_requirement(item)
    ))
    verifiable = bool(has_visible_problem and relevant and consistent is True and not tampering and not missing)
    risks = tuple(reason for reason, active in (
        ('visual_evidence_contradictory', consistent is False),
        ('visual_tampering_suspected', tampering),
    ) if active)
    issues = tuple(reason for reason, active in (
        ('visual_evidence_inconsistent', consistent is False),
        ('visual_tampering_suspected', tampering),
        ('visual_verification_limited', bool(review.get('verification_limitations'))),
        ('visual_problem_not_verified', not verifiable),
    ) if active)
    facts.update(
        visual_success=True,
        visual_verifiable=verifiable,
        evidence_consistent=consistent,
        visual_confidence=confidence,
        satisfied_evidence=('商品问题图片', '商品问题照片') if verifiable else (),
        missing_evidence=missing,
        risk_signals=risks,
        visual_issues=issues,
        image_review=dict(review),
        evidence_categories=tuple(dict.fromkeys(str(x).strip() for x in review.get('evidence_categories') or [] if str(x).strip())),
        observed_issue_types=tuple(dict.fromkeys(str(x).strip() for x in review.get('observed_issue_types') or [] if str(x).strip())),
        verification_limitations=tuple(dict.fromkeys(str(x).strip() for x in review.get('verification_limitations') or [] if str(x).strip())),
    )
    return facts


def review_assessment(
    context: TrustedCaseContext,
    policy: dict[str, Any],
    visual: dict[str, Any],
) -> ReviewAssessment:
    missing = list(visual['missing_evidence'])
    for item in policy['required_evidence']:
        if not is_core_evidence_requirement(item) or item in visual['satisfied_evidence'] or item in missing:
            continue
        if visual['visual_verifiable'] and any(token in item for token in ('图片', '照片', '截图')):
            continue
        missing.append(item)
    return ReviewAssessment(
        context_version=context.context_version,
        **policy,
        **{**visual, 'missing_evidence': tuple(missing)},
    )
