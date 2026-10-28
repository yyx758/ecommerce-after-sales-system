"""Describe new case input without reusing prior model verdicts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...facts import CaseContext
from ...facts.extractors import evidence_fingerprint


@dataclass(frozen=True)
class ContextDiff:
    new_claims: list[dict[str, Any]]
    new_evidence_refs: list[dict[str, str]]
    stale_policy_refs: list[str]
    conflicts: list[dict[str, Any]]

    @classmethod
    def build(cls, payload: dict[str, Any], context: CaseContext) -> "ContextDiff":
        summary = payload.get("history_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        current_policy = context.best_fact("ticket.policy_version")
        previous_policy = str(summary.get("policy_version") or "")
        stale = []
        if current_policy and previous_policy and previous_policy != str(current_policy.value):
            stale = [previous_policy]
        refs = []
        for attachment in payload.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            source = str(attachment.get("source") or "")
            if source:
                refs.append({"fingerprint": evidence_fingerprint(source),
                             "kind": str(attachment.get("kind") or "unknown")})
        message = str(payload.get("message") or "").strip()
        return cls(
            new_claims=[{"source_message_id": summary.get("current_message_id"),
                         "text": message, "trust": "claimed"}] if message else [],
            new_evidence_refs=refs, stale_policy_refs=stale,
            conflicts=[item.to_dict() for item in context.conflicts]
            + [item.to_dict() for item in context.discrepancies],
        )
