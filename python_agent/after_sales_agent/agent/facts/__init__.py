"""带来源的案件上下文：事实、信任阶梯与冲突暴露。"""

from .builder import CaseContextBuilder
from .extractors import (
    citations_of,
    facts_from_tool,
    trusted_policy_hits,
    user_claim_facts,
)
from .models import (
    CaseContext,
    CaseFact,
    FactConflict,
    FactDiscrepancy,
    SourceKind,
    TrustLevel,
    utc_now_iso,
)

__all__ = [
    "CaseContext",
    "CaseContextBuilder",
    "CaseFact",
    "FactConflict",
    "FactDiscrepancy",
    "SourceKind",
    "TrustLevel",
    "citations_of",
    "facts_from_tool",
    "trusted_policy_hits",
    "user_claim_facts",
    "utc_now_iso",
]
