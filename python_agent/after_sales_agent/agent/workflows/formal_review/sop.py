from __future__ import annotations

from dataclasses import dataclass

from .evaluators import is_core_evidence_requirement
from .contracts import (
    ReviewAssessment,
    ReviewProposal,
    TrustedCaseContext,
)


SOP_REVIEW_MODE = "SOP_AUTOMATED"
ESCALATED_REVIEW_MODE = "COMPLEX_REVIEW"


@dataclass(frozen=True)
class EscalationDecision:
    required: bool
    reasons: tuple[str, ...] = ()


class FormalReviewSop:
    """Deterministic orchestration policy for the routine review path."""

    @staticmethod
    def plan(context: TrustedCaseContext, issue: str) -> str:
        return ' '.join(dict.fromkeys(
            value for value in (issue.strip(), context.product_name) if value
        ))[:500]

    @staticmethod
    def assess_escalation(
        review: ReviewAssessment,
        *,
        minimum_review_confidence: float,
    ) -> EscalationDecision:
        reasons: list[str] = []
        if not review.policy_success:
            reasons.append("policy_check_failed")
        if not review.trusted_policy_eligible or not review.policy_version_matched:
            reasons.append("policy_not_authoritative")
        if (
            review.filter_level != "strict"
            or (
                not review.reranker_succeeded
                and review.retrieval_mode != "multi_query_rrf"
            )
            or not review.citations
        ):
            reasons.append("policy_retrieval_insufficient")
        if review.risk_signals or review.evidence_consistent is False:
            reasons.append("evidence_conflict")
        if not review.visual_success:
            reasons.append("evidence_check_failed")
        elif (
            not review.visual_verifiable
            or review.visual_confidence < minimum_review_confidence
        ):
            reasons.append("visual_evidence_uncertain")
        if any(
            is_core_evidence_requirement(item)
            for item in review.missing_evidence
        ):
            reasons.append("core_evidence_missing")
        return EscalationDecision(
            required=bool(reasons),
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def build_routine_proposal(
        review: ReviewAssessment,
    ) -> ReviewProposal:
        approvable = bool(
            review.policy_success
            and review.trusted_policy_eligible
            and review.policy_version_matched
            and review.visual_success
            and review.visual_verifiable
            and review.evidence_consistent is True
            and not review.risk_signals
        )
        return ReviewProposal(
            proposed_verdict=("APPROVE" if approvable else "MANUAL_REVIEW_REQUIRED"),
            reason=(
                "Policy and evidence checks satisfy the automated review SOP."
                if approvable
                else "The automated review SOP could not establish a reliable result."
            ),
            confidence=0.0,
            risk_reasons=(),
            assistant_reply=(
                "The automated initial review is complete."
                if approvable
                else "The request has been routed for manual review."
            ),
            model_confidence=0.0,
        )
