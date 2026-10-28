"""事实账本的数据模型：每条结论都带来源、时间与可信等级。

设计要点：

1. 事实不是自由文本，而是 ``(claim_key, value, trust, source_kind, source_ref,
   observed_at)`` 的结构化记录，回答时才能说清"依据哪条订单事实、哪段政策"。
2. 信任阶梯是硬顺序：Java 权威 > 工具上报 > 模型推断 > 用户主张。低等级事实
   永远不能覆盖高等级事实，冲突由 :mod:`.builder` 显式暴露而不是悄悄挑一个。
3. ``observed_at`` 一律使用 UTC 感知时间。数据库存 UTC，而 ``datetime.now()``
   返回 CST naive，直接混用会让"这条事实是什么时候观测到的"失去意义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class TrustLevel:
    """事实的可信等级，数值越大越可信。"""

    VERIFIED = "verified"
    REPORTED = "reported"
    INFERRED = "inferred"
    CLAIMED = "claimed"


TRUST_ORDER: dict[str, int] = {
    TrustLevel.VERIFIED: 4,
    TrustLevel.REPORTED: 3,
    TrustLevel.INFERRED: 2,
    TrustLevel.CLAIMED: 1,
}

#: 只有达到该等级的事实才允许参与"硬冲突"判定。
CONFLICT_TRUST_FLOOR = TRUST_ORDER[TrustLevel.REPORTED]


class SourceKind:
    """事实来源类别。"""

    ORDER = "order"
    TICKET = "ticket"
    MERCHANT_POLICY = "merchant_policy"
    POLICY = "policy"
    IMAGE = "image"
    USER = "user"


def utc_now_iso() -> str:
    """Return an explicit UTC timestamp for a fact observation."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CaseFact:
    """One sourced statement about the case under discussion."""

    claim_key: str
    value: Any
    trust: str
    source_kind: str
    source_ref: str
    observed_at: str = field(default_factory=utc_now_iso)
    detail: str = ""
    comparable: bool = True
    context_version: str = ""
    evidence_revision: int | None = None
    historical: bool = False
    source_refs: tuple[str, ...] = ()

    @property
    def trust_rank(self) -> int:
        return TRUST_ORDER.get(self.trust, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_key": self.claim_key,
            "value": self.value,
            "trust": self.trust,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_refs": list(self.source_refs or (self.source_ref,)),
            "entity_id": self.source_ref,
            "observed_at": self.observed_at,
            "detail": self.detail,
            "context_version": self.context_version or None,
            "evidence_revision": self.evidence_revision,
            "historical": self.historical,
        }
@dataclass(frozen=True)
class FactConflict:
    """Two trusted sources disagree about the same claim."""

    claim_key: str
    values: tuple[tuple[str, Any, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_key": self.claim_key,
            "values": [
                {"source_ref": ref, "value": value, "trust": trust}
                for ref, value, trust in self.values
            ],
        }

    def describe(self) -> str:
        rendered = "；".join(
            f"{ref}={value!r}（可信等级 {trust}）" for ref, value, trust in self.values
        )
        return f"{self.claim_key} 存在来源冲突：{rendered}"


@dataclass(frozen=True)
class FactDiscrepancy:
    """A low-trust statement disagrees with an authoritative fact."""

    claim_key: str
    authoritative_ref: str
    authoritative_value: Any
    disputed_ref: str
    disputed_value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_key": self.claim_key,
            "authoritative_ref": self.authoritative_ref,
            "authoritative_value": self.authoritative_value,
            "disputed_ref": self.disputed_ref,
            "disputed_value": self.disputed_value,
        }

    def describe(self) -> str:
        return (
            f"{self.claim_key}：已核实为 {self.authoritative_value!r}"
            f"（来源 {self.authoritative_ref}），"
            f"但 {self.disputed_ref} 声称 {self.disputed_value!r}"
        )


@dataclass
class CaseContext:
    """The accumulated, sourced view of one consultation."""

    facts: list[CaseFact] = field(default_factory=list)
    conflicts: list[FactConflict] = field(default_factory=list)
    discrepancies: list[FactDiscrepancy] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    def facts_for(self, claim_key: str) -> list[CaseFact]:
        return [fact for fact in self.facts if fact.claim_key == claim_key]

    def best_fact(self, claim_key: str) -> CaseFact | None:
        candidates = self.facts_for(claim_key)
        if not candidates:
            return None
        return max(candidates, key=lambda fact: (not fact.historical, fact.trust_rank, fact.observed_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [fact.to_dict() for fact in self.facts],
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            "discrepancies": [item.to_dict() for item in self.discrepancies],
            "unknowns": list(self.unknowns),
        }

    def render(self, *, max_facts: int = 40) -> str:
        """Render the ledger for a model prompt, highest trust first."""
        if not self.facts and not self.conflicts and not self.discrepancies:
            return "（本次会话没有取得任何可核验的案件事实）"
        ordered = sorted(
            self.facts,
            key=lambda fact: (-fact.trust_rank, fact.claim_key, fact.source_ref),
        )
        kept = ordered[:max_facts]
        lines = [f"已核实事实（共 {len(self.facts)} 条，展示 {len(kept)} 条）："]
        for fact in kept:
            lines.append(
                f"- {'[历史观测] ' if fact.historical else ''}{fact.claim_key} = {fact.value!r}"
                f"（来源 {fact.source_kind}/{fact.source_ref}，"
                f"可信等级 {fact.trust}，观测于 {fact.observed_at}）"
            )
        if len(ordered) > len(kept):
            lines.append(f"- （其余 {len(ordered) - len(kept)} 条低优先级事实已省略）")
        for conflict in self.conflicts:
            lines.append(f"- ⚠ {conflict.describe()}")
        for discrepancy in self.discrepancies:
            lines.append(f"- ⚠ {discrepancy.describe()}")
        if self.unknowns:
            lines.append("仍未知：" + "；".join(self.unknowns))
        return "\n".join(lines)
