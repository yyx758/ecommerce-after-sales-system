from __future__ import annotations

from threading import Barrier, Event

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from after_sales_agent.agent.workflows.formal_review import FormalReviewWorkflow
from after_sales_agent.agent.workflows.formal_review.graph import bind_review_cancellation
from after_sales_agent.interface.kafka_adapter import AfterSalesReviewKafkaConsumer
from after_sales_agent.tools import ToolResult


def payload() -> dict[str, object]:
    return {
        'user_id': '7',
        'session_id': '12',
        'ticket_id': '9001',
        'order_id': '8001',
        'review_request_id': 'review-1',
        'message': '请进行AI初审',
        'client_context': {'source': 'kafka'},
    }


def trusted_policy() -> dict[str, object]:
    return {
        'mode': 'hybrid_reranked',
        'filter_level': 'strict',
        'reranker_succeeded': True,
        'trusted_policy_eligible': True,
        'threshold': 0.55,
        'hits': [{
            'source_type': 'after_sales_policy',
            'merchant_code': 'MERCHANT_DEMO',
            'policy_version': 'v2',
            'trusted_policy_eligible': True,
            'relaxation_level': 'strict',
            'rerank_score': 0.9,
            'metadata': {'default_evidence': ['商品问题图片']},
            'citations': [{'source_code': 'POLICY-001', 'chunk_id': 'chunk-001'}],
        }],
    }


def visible_image() -> dict[str, object]:
    return {
        'success': True,
        'has_damage_area': True,
        'evidence_relevant': True,
        'evidence_consistent': True,
        'confidence': 0.93,
        'missing_visual_evidence': [],
        'items': [{'confidence': 0.93, 'issue_visible': True, 'evidence_relevance': 0.93}],
    }


class Tools:
    def __init__(self, *, policy=None, vision=None, attachments=True, barrier=None):
        self.policy = trusted_policy() if policy is None else policy
        self.vision = visible_image() if vision is None else vision
        self.attachments = attachments
        self.barrier = barrier
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        if name == 'get_after_sales_ticket':
            return ToolResult(ok=True, name=name, data={
                'ticket_id': '9001', 'order_id': '8001', 'status': 'PENDING_REVIEW',
                'merchant_code': 'MERCHANT_DEMO', 'policy_version': 'v2',
                'product_name': '蓝牙耳机', 'category': 'headphone',
                'after_sales_type': 'RETURN_REFUND', 'description': '耳机外壳破裂',
                'context_version': 'ctx-1',
                'evidence_urls': ['https://example.invalid/a.jpg'] if self.attachments else [],
            })
        if name in {'retrieve_knowledge', 'review_images'} and self.barrier:
            self.barrier.wait(timeout=5)
        if name == 'retrieve_knowledge':
            return ToolResult(ok=True, name=name, data=self.policy)
        if name == 'review_images':
            if isinstance(self.vision, Exception):
                return ToolResult(ok=False, name=name, error=str(self.vision), error_category='timeout')
            return ToolResult(ok=True, name=name, data=self.vision)
        if name == 'request_missing_evidence':
            return ToolResult(ok=True, name=name, data={'review_applied': True})
        if name == 'submit_ai_review':
            return ToolResult(ok=True, name=name, data={
                'review_applied': True, 'verdict': arguments['verdict'], 'status': 'PENDING_REVIEW',
            })
        raise AssertionError(name)


class Llm:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise ValueError('invalid model JSON')
        return {
            'proposed_verdict': 'MANUAL_REVIEW_REQUIRED',
            'reason': '人工复核', 'confidence': 0.1,
            'risk_reasons': ['uncertain'], 'assistant_reply': '转人工',
        }


def test_one_graph_parallel_nodes_and_one_assessment() -> None:
    barrier = Barrier(2)
    tools = Tools(barrier=barrier)
    workflow = FormalReviewWorkflow(tools=tools, llm=Llm())
    result = workflow.start(payload())

    assert result['raw']['gate_action'] == 'SUBMIT_REVIEW'
    assert result['raw']['review_assessment']['trusted_policy_eligible'] is True
    assert 'policy_assessment' not in result['raw']
    assert 'evidence_assessment' not in result['raw']
    assert [name for name, _ in tools.calls].count('submit_ai_review') == 1
    assert tools.calls[-1][1]['verdict'] == 'APPROVE'
    assert set(workflow.graph.nodes) >= {'policy_review', 'visual_review', 'review_synthesis'}


def test_missing_input_requests_evidence_before_parallel_review() -> None:
    tools = Tools(attachments=False)
    workflow = FormalReviewWorkflow(tools=tools, llm=Llm(), checkpointer=InMemorySaver())
    result = workflow.start(payload())

    assert result['raw']['gate_action'] == 'REQUEST_EVIDENCE'
    assert result['raw']['paused'] is True
    assert '商品问题图片' in result['evidence_needed']
    assert not any(name in {'retrieve_knowledge', 'review_images'} for name, _ in tools.calls)
    tools.attachments = True
    resumed = workflow.resume('review-1', {'evidence_revision': 1})
    assert resumed['raw']['gate_action'] == 'SUBMIT_REVIEW'


def test_model_timeout_fails_closed_without_second_evidence_request() -> None:
    tools = Tools(vision=TimeoutError('vision timed out'))
    result = FormalReviewWorkflow(tools=tools, llm=Llm()).start(payload())

    assert result['raw']['gate_action'] == 'MANUAL_REVIEW'
    assert result['raw']['review_assessment']['visual_success'] is False
    assert not any(name == 'request_missing_evidence' for name, _ in tools.calls)
    assert tools.calls[-1][1]['verdict'] == 'MANUAL_REVIEW_REQUIRED'


def test_unverifiable_image_goes_to_manual_not_repeated_evidence_request() -> None:
    tools = Tools(vision={**visible_image(), 'has_damage_area': False, 'evidence_relevant': False, 'items': []})
    result = FormalReviewWorkflow(tools=tools, llm=Llm()).start(payload())

    assert result['raw']['gate_action'] == 'MANUAL_REVIEW'
    assert not any(name == 'request_missing_evidence' for name, _ in tools.calls)


def test_complex_model_invalid_json_fails_closed() -> None:
    tools = Tools(policy={**trusted_policy(), 'trusted_policy_eligible': False, 'mode': 'hybrid_rrf_degraded'})
    llm = Llm(fail=True)
    result = FormalReviewWorkflow(tools=tools, llm=llm).start(payload())

    assert result['raw']['gate_action'] == 'MANUAL_REVIEW'
    assert result['raw']['failure_reason'] == 'review_synthesis_model_failed'
    assert tools.calls[-1][1]['verdict'] == 'MANUAL_REVIEW_REQUIRED'


def test_cancelled_slow_review_cannot_submit_late_approval() -> None:
    cancellation = Event()

    class SlowTools(Tools):
        def call(self, name, arguments):
            result = super().call(name, arguments)
            if name == 'review_images':
                cancellation.set()
            return result

    tools = SlowTools()
    workflow = FormalReviewWorkflow(tools=tools, llm=Llm())
    with bind_review_cancellation(cancellation):
        with pytest.raises(TimeoutError, match='cancelled'):
            workflow.start(payload())

    assert not any(name == 'submit_ai_review' for name, _ in tools.calls)


def test_stale_evidence_ends_review_without_returning_to_evidence_request() -> None:
    class StaleTools(Tools):
        def call(self, name, arguments):
            if name == 'submit_ai_review':
                self.calls.append((name, dict(arguments)))
                return ToolResult(ok=True, name=name, data={
                    'review_applied': False, 'review_reject_reason': 'STALE_EVIDENCE',
                })
            return super().call(name, arguments)

    tools = StaleTools()
    result = FormalReviewWorkflow(tools=tools, llm=Llm()).start(payload())

    assert result['raw']['paused'] is False
    assert result['raw']['failure_reason'] == 'stale_evidence'
    assert not any(name == 'request_missing_evidence' for name, _ in tools.calls)
    assert AfterSalesReviewKafkaConsumer._review_submit_outcome(result) == 'STALE_EVIDENCE'


def test_stale_precheck_evidence_request_ends_without_retry_loop() -> None:
    class StaleTools(Tools):
        def call(self, name, arguments):
            if name == 'request_missing_evidence':
                self.calls.append((name, dict(arguments)))
                return ToolResult(ok=True, name=name, data={
                    'review_reject_reason': 'STALE_EVIDENCE',
                })
            return super().call(name, arguments)

    tools = StaleTools(attachments=False)
    result = FormalReviewWorkflow(tools=tools, llm=Llm()).start(payload())

    assert result['raw']['paused'] is False
    assert [name for name, _ in tools.calls].count('request_missing_evidence') == 1
    assert AfterSalesReviewKafkaConsumer._review_submit_outcome(result) == 'STALE_EVIDENCE'
