from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ..llm_client import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from ..models import AfterSalesRequest, ConversationMessage, Order


@dataclass(frozen=True)
class QwenEmotionResult:
    label: str
    emotion_score: float
    confidence: float
    need_human_priority: bool
    reason: str
    raw: dict[str, Any]


class QwenEmotionBackend:
    """Emotion classification driven only by Qwen structured output."""

    KNOWN_LABELS = {"satisfied", "calm", "anxious", "dissatisfied", "angry"}
    SCORE_RANGES = {
        "satisfied": (0.0, 0.2),
        "calm": (0.0, 0.4),
        "anxious": (0.25, 0.7),
        "dissatisfied": (0.55, 0.9),
        "angry": (0.8, 1.0),
    }

    def __init__(self, config: OpenAICompatibleConfig | None = None) -> None:
        self.client = OpenAICompatibleClient(config or OpenAICompatibleConfig.from_env())

    def analyze(
        self,
        request: AfterSalesRequest,
        order: Order | None = None,
        *,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
    ) -> QwenEmotionResult:
        user_prompt = self._user_prompt(
            request=request,
            order=order,
            recent_history=recent_history,
            recent_user_messages=recent_user_messages,
        )

        raw = self.client.chat_json(
            system_prompt=self._system_prompt(),
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=260,
        )

        try:
            result = self._parse_result(raw)
        except LLMError as exc:
            repaired_raw = self._self_check(
                user_prompt=user_prompt,
                previous_raw=raw,
                previous_error=str(exc),
            )
            return self._parse_result(repaired_raw)

        if self._needs_self_check(result):
            repaired_raw = self._self_check(
                user_prompt=user_prompt,
                previous_raw=raw,
                previous_error="emotion label/score/handoff consistency check failed",
            )
            repaired_result = self._parse_result(repaired_raw)
            if not self._needs_self_check(repaired_result):
                return repaired_result

        return result

    @staticmethod
    def _system_prompt() -> str:
        schema = {
            "label": "satisfied|calm|anxious|dissatisfied|angry",
            "emotion_score": "0.0-1.0 之间的单个小数，越高表示越负面、越需要关注",
            "confidence": "0.0-1.0 之间的单个小数，表示你对本次判断的把握程度",
            "need_human_priority": "boolean，表示是否建议优先人工跟进",
            "reason": "一句简短中文说明判断依据",
        }
        return (
            "你是电商售后系统里的用户情绪分析器。"
            "请只根据用户当前消息、最近上下文、订单状态和已有补充信息，判断用户情绪。"
            "不要生成客服回复，不要输出解释性段落。"
            "你必须严格输出 JSON。"
            "label 只能是 satisfied、calm、anxious、dissatisfied、angry 五选一。"
            "emotion_score 必须是 0 到 1 之间的单个小数，例如 0.18、0.42、0.87。"
            "confidence 必须是 0 到 1 之间的单个小数，例如 0.66、0.91。"
            "need_human_priority 必须是 true 或 false。"
            "严禁输出区间、范围、文字说明或多个候选值。"
            "例如 emotion_score 不能写成 0.5-1.0、0.5~1.0、较高、medium。"
            "例如 confidence 不能写成 0.6-0.8、较高、high。"
            "label、emotion_score、need_human_priority 三者必须语义一致，不能互相矛盾。"
            "只允许类似下面这样的合法输出："
            '{"label":"anxious","emotion_score":0.62,"confidence":0.88,"need_human_priority":false,"reason":"用户表达着急，担心处理进度"}'
            "标签定义如下："
            "satisfied=明确满意、认可、感谢、积极反馈；"
            "calm=平静咨询、中性补充、普通追问；"
            "anxious=着急、催促、担心进度、急着使用；"
            "dissatisfied=明显不满、失望、体验差，但没有升级到激烈指责或威胁投诉；"
            "angry=愤怒、激烈指责、辱骂、威胁投诉、强烈要求升级处理。"
            "emotion_score 参考区间如下，并且必须与 label 保持一致："
            "satisfied=0.00-0.20；"
            "calm=0.00-0.40；"
            "anxious=0.25-0.70；"
            "dissatisfied=0.55-0.90；"
            "angry=0.80-1.00。"
            "need_human_priority 的判断规则："
            "satisfied 和 calm 通常为 false；"
            "anxious 只有在多次催促、明显升级风险时才可为 true；"
            "dissatisfied 和 angry 在涉及投诉、威胁升级、强烈不满时通常为 true。"
            f"输出字段说明：{json.dumps(schema, ensure_ascii=False)}"
        )

    @classmethod
    def _self_check_system_prompt(cls) -> str:
        return (
            "你是电商售后系统里的情绪结果质检器。"
            "你会收到同一条用户消息的原始上下文，以及上一轮情绪模型输出。"
            "你的任务不是解释，而是把上一轮结果修正成一份合法、稳定、语义一致的 JSON。"
            "只能输出一个 JSON 对象，字段固定为 label、emotion_score、confidence、need_human_priority、reason。"
            "label 只能是 satisfied、calm、anxious、dissatisfied、angry。"
            "emotion_score、confidence 必须是 0 到 1 之间的单个小数。"
            "need_human_priority 必须是 true 或 false。"
            "如果上一轮输出结构错了、标签和分数矛盾、或转人工判断不合理，请直接修正。"
            "修正规则：satisfied=0.00-0.20，calm=0.00-0.40，anxious=0.25-0.70，dissatisfied=0.55-0.90，angry=0.80-1.00。"
            "例如“好的谢谢你，明白了”不应给出高负面分；“你们一直不处理，我要投诉12315”不应给出 calm 或 satisfied。"
        )

    @staticmethod
    def _user_prompt(
        *,
        request: AfterSalesRequest,
        order: Order | None,
        recent_history: tuple[ConversationMessage, ...],
        recent_user_messages: tuple[str, ...],
    ) -> str:
        payload = {
            "current_message": request.message,
            "reason": request.reason,
            "description": request.description,
            "human_request_count": request.human_request_count,
            "order": {
                "status": order.status.value if order else "",
                "after_sales_status": order.after_sales_status.value if order else "",
                "refund_status": order.refund_status if order else "",
                "logistics_status": order.logistics_status if order else "",
                "merchant_rejected_before": order.merchant_rejected_before if order else False,
            },
            "recent_history": [
                {"role": message.role, "content": message.content}
                for message in recent_history[-8:]
                if message.content
            ],
            "recent_user_messages": [message for message in recent_user_messages[-5:] if message],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _self_check(self, *, user_prompt: str, previous_raw: dict[str, Any], previous_error: str) -> dict[str, Any]:
        repair_payload = {
            "original_context": json.loads(user_prompt),
            "previous_output": previous_raw,
            "previous_error": previous_error,
        }
        return self.client.chat_json(
            system_prompt=self._self_check_system_prompt(),
            user_prompt=json.dumps(repair_payload, ensure_ascii=False, indent=2),
            temperature=0.0,
            max_tokens=260,
        )

    @classmethod
    def _parse_result(cls, raw: dict[str, Any]) -> QwenEmotionResult:
        if "assistant_reply" in raw and len(raw) == 1:
            raise LLMError("emotion model did not return structured JSON")

        label = cls._normalize_label(raw.get("label"))
        if label not in cls.KNOWN_LABELS:
            raise LLMError(f"invalid emotion label: {label}")

        emotion_score = cls._parse_required_float(raw.get("emotion_score"), "emotion_score")
        confidence = cls._parse_required_float(raw.get("confidence"), "confidence")
        need_human_priority = cls._parse_required_bool(raw.get("need_human_priority"), "need_human_priority")

        return QwenEmotionResult(
            label=label,
            emotion_score=max(0.0, min(1.0, emotion_score)),
            confidence=max(0.0, min(1.0, confidence)),
            need_human_priority=need_human_priority,
            reason=str(raw.get("reason") or "").strip(),
            raw=raw,
        )

    @classmethod
    def _needs_self_check(cls, result: QwenEmotionResult) -> bool:
        score_min, score_max = cls.SCORE_RANGES[result.label]
        if result.emotion_score < score_min or result.emotion_score > score_max:
            return True
        if result.label in {"satisfied", "calm"} and result.need_human_priority:
            return True
        if result.label == "angry" and not result.need_human_priority:
            return True
        return False

    @staticmethod
    def _parse_required_float(value: Any, field_name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise LLMError(f"invalid or missing {field_name}: {value}") from exc

    @staticmethod
    def _parse_required_bool(value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        raise LLMError(f"invalid or missing {field_name}: {value}")

    @classmethod
    def _normalize_label(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in cls.KNOWN_LABELS:
            return text

        candidates = [item.strip() for item in text.replace("/", "|").replace(",", "|").split("|") if item.strip()]
        known = [item for item in candidates if item in cls.KNOWN_LABELS]
        if len(known) == 1:
            return known[0]
        return text
