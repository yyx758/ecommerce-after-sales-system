from __future__ import annotations

from dataclasses import dataclass, field

from .emotion_policy import EmotionPolicyConfig, load_emotion_policy_config
from .models import (
    AfterSalesRequest,
    ConversationMessage,
    EmotionAnalysisResult,
    EmotionLabel,
    EmotionTurn,
    Order,
)


@dataclass(frozen=True)
class EmotionAgent:
    policy: EmotionPolicyConfig = field(default_factory=load_emotion_policy_config)

    def analyze(
        self,
        request: AfterSalesRequest,
        order: Order | None = None,
        *,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
    ) -> EmotionAnalysisResult:
        history_turns = self._build_history_turns(recent_history, recent_user_messages)
        current_text = self._build_current_text(request)
        current_turn = self._score_text(
            current_text,
            order=order,
            human_request_count=request.human_request_count,
            created_time=request.requested_at,
            from_history=False,
        )

        timeline = tuple(history_turns + [current_turn]) if current_turn.text else tuple(history_turns)
        trend = self._resolve_trend(timeline)
        consecutive_rises = self._count_consecutive_rises(timeline)
        escalation_signals = self._build_escalation_signals(
            timeline=timeline,
            trend=trend,
            consecutive_rises=consecutive_rises,
            human_request_count=request.human_request_count,
        )

        need_human_priority = current_turn.label == EmotionLabel.ANGRY or bool(escalation_signals)
        return EmotionAnalysisResult(
            label=current_turn.label,
            score=current_turn.score,
            triggers=current_turn.triggers,
            need_human_priority=need_human_priority,
            reply_tone=self._reply_tone(current_turn.label, escalation_signals),
            comfort_prefix=self._comfort_prefix(current_turn.label),
            comfort_examples=self._comfort_examples(current_turn.label),
            timeline=timeline,
            trend=trend,
            consecutive_rises=consecutive_rises,
            escalation_signals=escalation_signals,
        )

    @staticmethod
    def _build_current_text(request: AfterSalesRequest) -> str:
        return " ".join(
            part.strip() for part in (request.message, request.reason, request.description) if part
        ).strip()

    def _build_history_turns(
        self,
        recent_history: tuple[ConversationMessage, ...],
        recent_user_messages: tuple[str, ...],
    ) -> list[EmotionTurn]:
        turns: list[EmotionTurn] = []
        for message in recent_history:
            if message.role != "user":
                continue
            text = str(message.content or "").strip()
            if not text:
                continue
            turns.append(
                self._score_text(
                    text,
                    order=None,
                    human_request_count=0,
                    created_time=message.create_time,
                    from_history=True,
                )
            )

        if not turns:
            for text in recent_user_messages:
                cleaned = str(text or "").strip()
                if not cleaned:
                    continue
                turns.append(
                    self._score_text(
                        cleaned,
                        order=None,
                        human_request_count=0,
                        created_time=None,
                        from_history=True,
                    )
                )
        return turns

    def _score_text(
        self,
        text: str,
        *,
        order: Order | None,
        human_request_count: int,
        created_time,
        from_history: bool,
    ) -> EmotionTurn:
        cleaned = text.strip()
        score = 0
        triggers: list[str] = []

        for rule in self.policy.keyword_rules:
            score += self._apply_keyword_rule(cleaned, rule.keywords, rule.score, rule.extra_per_match, triggers)
            if any(keyword in cleaned for keyword in rule.keywords):
                triggers.append(rule.name)

        for combo_rule in self.policy.combo_rules:
            if self._combo_matched(cleaned, combo_rule.groups):
                score += combo_rule.bonus
                triggers.append(combo_rule.name)

        score += self._punctuation_score(cleaned)

        if human_request_count >= 1:
            score += self.policy.weights.human_request_first
            triggers.append("ask_human")
        if human_request_count >= 2:
            score += self.policy.weights.human_request_repeat
            triggers.append("repeat_ask_human")

        if order is not None:
            status_text = f"{order.refund_status} {order.logistics_status}"
            if any(keyword in status_text for keyword in ("超时", "未更新", "停滞", "延迟", "异常", "过久")):
                score += self.policy.weights.timeout
                triggers.append("timeout")
            if order.merchant_rejected_before:
                score += self.policy.weights.merchant_rejected
                triggers.append("merchant_rejected")

        final_score = min(score, 100)
        label = self._resolve_label(final_score)
        return EmotionTurn(
            text=cleaned,
            label=label,
            score=final_score,
            triggers=tuple(dict.fromkeys(triggers)),
            created_time=created_time,
            from_history=from_history,
        )

    @staticmethod
    def _apply_keyword_rule(
        text: str,
        keywords: tuple[str, ...],
        base_score: int,
        extra_per_match: int,
        triggers: list[str],
    ) -> int:
        matched = [keyword for keyword in keywords if keyword in text]
        if not matched:
            return 0
        triggers.extend(matched)
        return base_score + max(0, len(matched) - 1) * extra_per_match

    @staticmethod
    def _combo_matched(text: str, groups: tuple[tuple[str, ...], ...]) -> bool:
        return all(any(keyword in text for keyword in group) for group in groups)

    def _punctuation_score(self, text: str) -> int:
        score = 0
        if "!!!" in text or "???" in text or "！！" in text:
            score += self.policy.weights.punctuation_triple
        if text.count("!") >= 3 or text.count("！") >= 3:
            score += self.policy.weights.punctuation_exclamation
        if text.count("?") >= 3 or text.count("？") >= 3:
            score += self.policy.weights.punctuation_question
        return score

    def _resolve_label(self, score: int) -> EmotionLabel:
        thresholds = self.policy.thresholds
        if score >= thresholds.angry:
            return EmotionLabel.ANGRY
        if score >= thresholds.dissatisfied:
            return EmotionLabel.DISSATISFIED
        if score >= thresholds.anxious:
            return EmotionLabel.ANXIOUS
        return EmotionLabel.CALM

    @staticmethod
    def _level(label: EmotionLabel) -> int:
        return {
            EmotionLabel.CALM: 0,
            EmotionLabel.ANXIOUS: 1,
            EmotionLabel.DISSATISFIED: 2,
            EmotionLabel.ANGRY: 3,
        }[label]

    def _resolve_trend(self, timeline: tuple[EmotionTurn, ...]) -> str:
        if len(timeline) < 2:
            return "stable"
        previous = self._level(timeline[-2].label)
        current = self._level(timeline[-1].label)
        if current > previous:
            return "up"
        if current < previous:
            return "down"
        return "stable"

    def _count_consecutive_rises(self, timeline: tuple[EmotionTurn, ...]) -> int:
        if len(timeline) < 2:
            return 0
        rises = 0
        for index in range(len(timeline) - 1, 0, -1):
            current = self._level(timeline[index].label)
            previous = self._level(timeline[index - 1].label)
            if current > previous:
                rises += 1
                continue
            break
        return rises

    def _build_escalation_signals(
        self,
        *,
        timeline: tuple[EmotionTurn, ...],
        trend: str,
        consecutive_rises: int,
        human_request_count: int,
    ) -> tuple[str, ...]:
        if not timeline:
            return ()

        signals: list[str] = []
        current = timeline[-1]
        previous = timeline[-2] if len(timeline) >= 2 else None

        if consecutive_rises >= self.policy.trend.consecutive_rises_trigger:
            signals.append("consecutive_rises")
        if (
            self.policy.trend.calm_to_angry_enabled
            and previous
            and previous.label == EmotionLabel.CALM
            and current.label == EmotionLabel.ANGRY
        ):
            signals.append("jump_calm_to_angry")
        if human_request_count >= 2 and current.label in {EmotionLabel.DISSATISFIED, EmotionLabel.ANGRY}:
            signals.append("repeated_human_request_without_relief")
        if trend == "up" and current.label == EmotionLabel.ANGRY:
            signals.append("anger_uptrend")

        return tuple(dict.fromkeys(signals))

    @staticmethod
    def _reply_tone(label: EmotionLabel, escalation_signals: tuple[str, ...]) -> str:
        if escalation_signals and label in {EmotionLabel.DISSATISFIED, EmotionLabel.ANGRY}:
            return "priority_human_support"
        return {
            EmotionLabel.CALM: "clear",
            EmotionLabel.ANXIOUS: "comfort_and_progress",
            EmotionLabel.DISSATISFIED: "comfort_and_action",
            EmotionLabel.ANGRY: "priority_human_support",
        }[label]

    @staticmethod
    def _comfort_prefix(label: EmotionLabel) -> str:
        return {
            EmotionLabel.CALM: "",
            EmotionLabel.ANXIOUS: "您好，理解您现在比较着急，",
            EmotionLabel.DISSATISFIED: "您好，确实让您久等了，",
            EmotionLabel.ANGRY: "您好，很抱歉给您带来不好的体验，",
        }[label]

    @staticmethod
    def _comfort_examples(label: EmotionLabel) -> tuple[str, ...]:
        return {
            EmotionLabel.CALM: (
                "我先帮您看当前状态。",
                "这边按页面流程继续推进。",
            ),
            EmotionLabel.ANXIOUS: (
                "我先帮您确认当前进度。",
                "状态一更新我会第一时间同步您。",
            ),
            EmotionLabel.DISSATISFIED: (
                "这边我先帮您把流程往前推进。",
                "我会继续帮您跟进处理结果。",
            ),
            EmotionLabel.ANGRY: (
                "我先帮您优先处理。",
                "如有需要也可以继续转人工跟进。",
            ),
        }[label]
