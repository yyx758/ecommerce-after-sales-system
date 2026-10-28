from __future__ import annotations

from after_sales_agent.agent.safety_guards import (
    allow_ai_review_submit,
    best_policy_score,
    is_explicit_human_request,
    policy_hit_score,
)


def test_explicit_human_request_is_detected_in_the_current_message() -> None:
    assert is_explicit_human_request("请帮我转人工客服") is True
    assert is_explicit_human_request("退款需要准备哪些材料") is False


def test_explicit_human_request_is_remembered_from_the_recent_history() -> None:
    history = [{"role": "user", "content": "我想联系人工客服"}]

    assert is_explicit_human_request("还有其他方式吗", history) is True


def test_history_entries_from_the_assistant_are_ignored() -> None:
    history = [{"role": "assistant", "content": "需要转人工客服吗？"}]

    assert is_explicit_human_request("退款需要准备哪些材料", history) is False


def test_only_the_trusted_kafka_path_may_submit_a_verdict() -> None:
    assert allow_ai_review_submit({"client_context": {"source": "kafka"}}) is True
    assert allow_ai_review_submit({"client_context": {"source": "java_gateway"}}) is False
    assert allow_ai_review_submit({}) is False


def test_policy_hit_score_prefers_the_calibrated_value() -> None:
    assert policy_hit_score({"calibrated_policy_confidence": 0.8, "rerank_score": 0.2}) == 0.8
    assert policy_hit_score({"rerank_score": 0.6}) == 0.6
    assert policy_hit_score({}) == 0.0
    assert policy_hit_score({"rerank_score": "not-a-number"}) == 0.0


def test_best_policy_score_is_the_best_hit() -> None:
    assert best_policy_score([{"rerank_score": 0.4}, {"rerank_score": 0.9}]) == 0.9
    assert best_policy_score([]) == 0.0
