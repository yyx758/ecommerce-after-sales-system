from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
from typing import Any


@dataclass(frozen=True)
class EmotionThresholds:
    anxious: int = 20
    dissatisfied: int = 45
    angry: int = 85


@dataclass(frozen=True)
class EmotionKeywordRule:
    name: str
    keywords: tuple[str, ...]
    score: int
    extra_per_match: int = 3


@dataclass(frozen=True)
class EmotionComboRule:
    name: str
    groups: tuple[tuple[str, ...], ...]
    bonus: int


@dataclass(frozen=True)
class EmotionWeights:
    punctuation_triple: int = 8
    punctuation_exclamation: int = 4
    punctuation_question: int = 4
    human_request_first: int = 8
    human_request_repeat: int = 12
    timeout: int = 10
    merchant_rejected: int = 12


@dataclass(frozen=True)
class EmotionTrendPolicy:
    consecutive_rises_trigger: int = 2
    calm_to_angry_enabled: bool = True


@dataclass(frozen=True)
class EmotionPolicyConfig:
    thresholds: EmotionThresholds = field(default_factory=EmotionThresholds)
    keyword_rules: tuple[EmotionKeywordRule, ...] = field(default_factory=tuple)
    combo_rules: tuple[EmotionComboRule, ...] = field(default_factory=tuple)
    weights: EmotionWeights = field(default_factory=EmotionWeights)
    trend: EmotionTrendPolicy = field(default_factory=EmotionTrendPolicy)

    @classmethod
    def default(cls) -> "EmotionPolicyConfig":
        return cls(
            keyword_rules=(
                EmotionKeywordRule("complaint", ("投诉", "举报", "差评", "骗人", "诈骗"), 40, 3),
                EmotionKeywordRule("anger", ("生气", "气死", "太过分", "受不了", "你们到底", "不满意", "离谱"), 30, 3),
                EmotionKeywordRule("stalled", ("太慢了", "一直没人处理", "没人处理", "到底怎么处理", "这也太慢了"), 22, 2),
                EmotionKeywordRule("progress_query", ("怎么还", "一直没", "多久了", "快点", "催一下", "什么时候到账", "还没处理"), 15, 2),
            ),
            combo_rules=(
                EmotionComboRule(
                    "complaint_plus_human",
                    (("投诉", "差评", "举报"), ("人工", "客服", "真人")),
                    10,
                ),
                EmotionComboRule(
                    "fraud_complaint_combo",
                    (("骗人", "诈骗"), ("投诉", "举报", "差评")),
                    15,
                ),
                EmotionComboRule(
                    "stalled_progress_combo",
                    (("一直没人处理", "没人处理", "还没处理"), ("太慢了", "快点", "催一下")),
                    8,
                ),
            ),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmotionPolicyConfig":
        defaults = cls.default()
        thresholds = _build_thresholds(data.get("thresholds"), defaults.thresholds)
        weights = _build_weights(data.get("weights"), defaults.weights)
        trend = _build_trend(data.get("trend"), defaults.trend)
        keyword_rules = tuple(
            EmotionKeywordRule(
                name=str(item.get("name") or f"rule_{index}"),
                keywords=tuple(str(keyword) for keyword in item.get("keywords") or ()),
                score=int(item.get("score") or 0),
                extra_per_match=int(item.get("extra_per_match") or 3),
            )
            for index, item in enumerate(data.get("keyword_rules") or [])
            if isinstance(item, dict)
        )
        combo_rules = tuple(
            EmotionComboRule(
                name=str(item.get("name") or f"combo_{index}"),
                groups=tuple(
                    tuple(str(keyword) for keyword in group)
                    for group in (item.get("groups") or [])
                    if isinstance(group, (list, tuple))
                ),
                bonus=int(item.get("bonus") or 0),
            )
            for index, item in enumerate(data.get("combo_rules") or [])
            if isinstance(item, dict)
        )
        return cls(
            thresholds=thresholds,
            keyword_rules=keyword_rules or defaults.keyword_rules,
            combo_rules=combo_rules or defaults.combo_rules,
            weights=weights,
            trend=trend,
        )


def load_emotion_policy_config(path: str | Path | None = None) -> EmotionPolicyConfig:
    resolved_path = _resolve_emotion_policy_path(path)
    if not resolved_path.exists():
        return EmotionPolicyConfig.default()
    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return EmotionPolicyConfig.default()
        return EmotionPolicyConfig.from_dict(data)
    except Exception:
        return EmotionPolicyConfig.default()


def _resolve_emotion_policy_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.getenv("EMOTION_POLICY_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[1] / "config" / "emotion_policy.json"


def _build_thresholds(raw: Any, default: EmotionThresholds) -> EmotionThresholds:
    if not isinstance(raw, dict):
        return default
    return EmotionThresholds(
        anxious=int(raw.get("anxious", default.anxious)),
        dissatisfied=int(raw.get("dissatisfied", default.dissatisfied)),
        angry=int(raw.get("angry", default.angry)),
    )


def _build_weights(raw: Any, default: EmotionWeights) -> EmotionWeights:
    if not isinstance(raw, dict):
        return default
    return EmotionWeights(
        punctuation_triple=int(raw.get("punctuation_triple", default.punctuation_triple)),
        punctuation_exclamation=int(raw.get("punctuation_exclamation", default.punctuation_exclamation)),
        punctuation_question=int(raw.get("punctuation_question", default.punctuation_question)),
        human_request_first=int(raw.get("human_request_first", default.human_request_first)),
        human_request_repeat=int(raw.get("human_request_repeat", default.human_request_repeat)),
        timeout=int(raw.get("timeout", default.timeout)),
        merchant_rejected=int(raw.get("merchant_rejected", default.merchant_rejected)),
    )


def _build_trend(raw: Any, default: EmotionTrendPolicy) -> EmotionTrendPolicy:
    if not isinstance(raw, dict):
        return default
    return EmotionTrendPolicy(
        consecutive_rises_trigger=int(
            raw.get("consecutive_rises_trigger", default.consecutive_rises_trigger)
        ),
        calm_to_angry_enabled=bool(raw.get("calm_to_angry_enabled", default.calm_to_angry_enabled)),
    )
