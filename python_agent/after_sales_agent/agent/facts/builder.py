"""事实账本构建器：累积事实、去重、暴露冲突。

冲突分两级，都必须显式告诉模型，不能让模型自己挑一个信：

* **硬冲突**（``conflicts``）：两个可信等级不低于 ``REPORTED`` 的来源对同一
  ``claim_key`` 给出不同值——订单状态在两次查询间变了、工单状态与订单挂载状态
  不一致等。
* **软差异**（``discrepancies``）：高可信来源与低可信来源对同一 ``claim_key``
  给出不同值。低可信来源不能推翻高可信来源，但差异本身要写进回答。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from .extractors import facts_from_tool
from .models import (
    CONFLICT_TRUST_FLOOR,
    CaseContext,
    CaseFact,
    FactConflict,
    FactDiscrepancy,
    TrustLevel,
)


class CaseContextBuilder:
    """Accumulate sourced facts and resolve them into a :class:`CaseContext`."""

    def __init__(self, *, max_facts: int = 40) -> None:
        self._facts: list[CaseFact] = []
        self._unknowns: list[str] = []
        self._max_facts = max_facts
        self._confirmed: dict[tuple[str, str], tuple[Any, str]] = {}

    def add_facts(self, facts: Iterable[CaseFact]) -> list[CaseFact]:
        """Add facts, dropping exact duplicates of the same source."""
        added: list[CaseFact] = []
        for fact in facts:
            duplicate = any(
                existing.claim_key == fact.claim_key
                and existing.value == fact.value
                and existing.source_ref == fact.source_ref
                and existing.source_kind == fact.source_kind
                and existing.context_version == fact.context_version
                for existing in self._facts
            )
            if duplicate:
                for index, existing in enumerate(self._facts):
                    if (existing.claim_key == fact.claim_key and existing.value == fact.value
                            and existing.source_ref == fact.source_ref
                            and existing.source_kind == fact.source_kind
                            and existing.context_version == fact.context_version):
                        refs = tuple(dict.fromkeys([*(existing.source_refs or (existing.source_ref,)),
                                                        *(fact.source_refs or (fact.source_ref,))]))
                        self._facts[index] = replace(existing, source_refs=refs)
                        break
                continue
            self._facts.append(fact)
            added.append(fact)
        return added

    def add_tool_result(self, tool_name: str, data: Any) -> list[CaseFact]:
        """Add every fact carried by one tool result."""
        return self.add_facts(
            replace(fact, source_refs=(f"{tool_name}:{fact.source_ref}",))
            for fact in facts_from_tool(tool_name, data)
        )

    def add_unknown(self, text: str) -> None:
        """Record something the agent still could not establish."""
        value = str(text or "").strip()
        if value and value not in self._unknowns:
            self._unknowns.append(value)

    def confirm_current(self, source_kind: str, source_ref: str, claim_key: str,
                        value: Any, context_version: str = "") -> None:
        """Record a single Java requery; it cannot resolve same-version contradictions."""
        self._confirmed[(claim_key, source_ref)] = (value, context_version)

    @property
    def facts(self) -> list[CaseFact]:
        return list(self._facts)

    def build(self) -> CaseContext:
        """Resolve the accumulated facts into conflicts and discrepancies."""
        conflicts = self._detect_conflicts()
        discrepancies = self._detect_discrepancies()
        discrepancies.extend(self._cross_check_order_ticket())
        display_facts = [
            replace(fact, historical=True)
            if (fact.claim_key, fact.source_ref) in self._confirmed
            and fact.value != self._confirmed[(fact.claim_key, fact.source_ref)][0]
            else fact
            for fact in self._facts
        ]
        ordered = sorted(
            display_facts,
            key=lambda fact: (-fact.trust_rank, fact.claim_key, fact.source_ref),
        )
        kept = ordered[: self._max_facts]
        return CaseContext(
            facts=kept,
            conflicts=conflicts,
            discrepancies=discrepancies,
            unknowns=list(self._unknowns),
        )

    def _detect_conflicts(self) -> list[FactConflict]:
        grouped: dict[tuple[str, str], list[CaseFact]] = {}
        for fact in self._facts:
            if not fact.comparable:
                continue
            if fact.trust_rank < CONFLICT_TRUST_FLOOR:
                continue
            entity = fact.source_ref if fact.source_kind in {"order", "ticket"} else ""
            grouped.setdefault((fact.claim_key, entity), []).append(fact)
        conflicts: list[FactConflict] = []
        for (claim_key, _entity), facts in sorted(grouped.items()):
            distinct = {repr(fact.value) for fact in facts}
            if len(distinct) < 2:
                continue
            confirmed = self._confirmed.get((claim_key, _entity))
            if confirmed is not None:
                current_value, current_version = confirmed
                same_version_disagreement = any(
                    left.context_version == right.context_version
                    and left.value != right.value
                    for left in facts for right in facts
                    if left is not right and left.context_version
                )
                if (not same_version_disagreement
                        and current_value in [fact.value for fact in facts]
                        and (not current_version or any(
                            fact.value == current_value and fact.context_version == current_version
                            for fact in facts))):
                    continue
            conflicts.append(
                FactConflict(
                    claim_key=claim_key,
                    values=tuple(
                        (fact.source_ref, fact.value, fact.trust) for fact in facts
                    ),
                )
            )
        return conflicts

    def _detect_discrepancies(self) -> list[FactDiscrepancy]:
        grouped: dict[tuple[str, str], list[CaseFact]] = {}
        for fact in self._facts:
            if fact.comparable:
                entity = fact.source_ref if fact.source_kind in {"order", "ticket"} else ""
                grouped.setdefault((fact.claim_key, entity), []).append(fact)
        discrepancies: list[FactDiscrepancy] = []
        for (claim_key, _entity), facts in sorted(grouped.items()):
            ordered = sorted(facts, key=lambda fact: -fact.trust_rank)
            authoritative = ordered[0]
            for other in ordered[1:]:
                if other.trust_rank >= authoritative.trust_rank:
                    continue
                if other.value == authoritative.value:
                    continue
                discrepancies.append(
                    FactDiscrepancy(
                        claim_key=claim_key,
                        authoritative_ref=authoritative.source_ref,
                        authoritative_value=authoritative.value,
                        disputed_ref=other.source_ref,
                        disputed_value=other.value,
                    )
                )
                break
        return discrepancies

    def _cross_check_order_ticket(self) -> list[FactDiscrepancy]:
        """Order index and ticket snapshot must agree on the linked ticket."""
        by_source: dict[tuple[str, str], dict[str, CaseFact]] = {}
        for fact in self._facts:
            if fact.source_kind in {"order", "ticket"}:
                by_source.setdefault((fact.source_kind, fact.source_ref), {})[fact.claim_key] = fact
        discrepancies: list[FactDiscrepancy] = []
        orders = [facts for (kind, _), facts in by_source.items() if kind == "order"]
        tickets = [facts for (kind, _), facts in by_source.items() if kind == "ticket"]
        for ticket in tickets:
            ticket_id, ticket_status = ticket.get("ticket.id"), ticket.get("ticket.status")
            if not (ticket_id and ticket_status):
                continue
            for order in orders:
                linked_id = order.get("order.existing_ticket_id")
                linked_status = order.get("order.existing_ticket_status")
                if not (linked_id and linked_status) or linked_id.value != ticket_id.value:
                    continue
                if linked_status.value != ticket_status.value:
                    discrepancies.append(FactDiscrepancy(
                        claim_key="ticket.status",
                        authoritative_ref=ticket_status.source_ref,
                        authoritative_value=ticket_status.value,
                        disputed_ref=linked_id.source_ref,
                        disputed_value=linked_status.value,
                    ))
        return discrepancies

    def policy_evidence_required(self) -> tuple[str, ...]:
        """The credential list the trusted policy demands, if any."""
        for fact in self._facts:
            if fact.claim_key == "policy.evidence_required":
                value = fact.value
                if isinstance(value, (list, tuple)):
                    return tuple(str(item) for item in value)
        return ()

    def policy_citations(self) -> list[str]:
        """The source codes of the trusted policy citations."""
        for fact in self._facts:
            if fact.claim_key == "policy.citations":
                value = fact.value
                if isinstance(value, (list, tuple)):
                    return [str(item) for item in value if str(item).strip()]
        return []

    def has_trusted_policy(self) -> bool:
        """Whether any trusted policy fact was recorded."""
        return any(
            fact.claim_key.startswith("policy.evidence.") and fact.value
            for fact in self._facts
        )

    def trusted_trust_floor(self) -> int:
        """The trust floor used by the hard-conflict rule."""
        return CONFLICT_TRUST_FLOOR


__all__ = [
    "CaseContextBuilder",
    "TrustLevel",
]
