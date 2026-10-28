from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..agent.safety_guards import (
    allow_ai_review_submit,
    best_policy_score,
    is_explicit_human_request,
)
from ..agent.workflows.formal_review.confidence import apply_deterministic_confidence
from ..agent.workflows.formal_review.contracts import (
    ReviewAssessment,
    ReviewProposal,
    TrustedCaseContext,
)
from ..agent.workflows.formal_review.evaluators import (
    policy_facts,
    trusted_policy_hits,
)
from ..application.request_payload_adapter import build_langgraph_entry_payload
from ..integrations.java_tool_client import JavaToolClient
from ..tools import ToolResult


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not value.get("id") or not value.get("type"):
            raise ValueError(f"Invalid evaluation case at line {line_number}")
        cases.append(value)
    return cases


def evaluate_cases(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    results = [_evaluate_case(case) for case in cases]
    handoff_positive = [row for row in results if row["type"] == "human_handoff" and row["expected"] is True]
    handoff_true_positive = sum(row["passed"] for row in handoff_positive)
    unsafe_policy_cases = [
        row for row in results
        if row["type"] == "policy_gate" and row["expected"] is False
    ]
    safety_violations = sum(bool(row["actual"]) for row in unsafe_policy_cases)
    passed = sum(row["passed"] for row in results)
    total = len(results)
    handoff_recall = handoff_true_positive / len(handoff_positive) if handoff_positive else 1.0
    report = {
        "dataset_version": "2.0",
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "handoff_recall": round(handoff_recall, 4),
        "auto_review_safety_violations": safety_violations,
        "quality_gates": {
            "pass_rate_min": 1.0,
            "handoff_recall_min": 0.95,
            "auto_review_safety_violations_max": 0,
        },
        "results": results,
    }
    report["quality_gate_passed"] = bool(
        report["pass_rate"] >= report["quality_gates"]["pass_rate_min"]
        and report["handoff_recall"] >= report["quality_gates"]["handoff_recall_min"]
        and safety_violations <= report["quality_gates"]["auto_review_safety_violations_max"]
    )
    return report


def _review_context(order: dict[str, Any]) -> TrustedCaseContext:
    """Build the review context an evaluation case describes."""
    return TrustedCaseContext(
        user_id=str(order.get("user_id") or ""),
        session_id=None,
        ticket_id=str(order.get("ticket_id") or order.get("order_id") or ""),
        order_id=str(order.get("order_id") or ""),
        ticket_status=str(order.get("status") or ""),
        merchant_code=order.get("merchant_code") or None,
        policy_version=order.get("policy_version") or None,
        product_name=order.get("product_name") or None,
        product_category=order.get("category") or None,
        after_sales_type=order.get("after_sales_type") or None,
        issue_description="",
        business_time=order.get("after_sales_applied_at") or order.get("create_time"),
        context_version=str(order.get("context_version") or "evaluation"),
        evidence_revision=int(order.get("evidence_revision") or 0),
        request_source="kafka",
    )


def _assessment(case: dict[str, Any]) -> ReviewAssessment:
    """Build the review assessment an evaluation case describes."""
    return ReviewAssessment(
        context_version="evaluation",
        policy_success=bool(case.get("policy_success", True)),
        trusted_policy_eligible=bool(case.get("policy_trusted", False)),
        policy_version_matched=bool(case.get("policy_version_matched", False)),
        filter_level=case.get("filter_level"),
        reranker_succeeded=bool(case.get("reranker_succeeded", False)),
        retrieval_mode=case.get("retrieval_mode"),
        policy_match_score=float(case.get("policy_match_score") or 0.0),
        visual_success=bool(case.get("visual_success", False)),
        visual_verifiable=bool(case.get("visual_verifiable", False)),
        evidence_consistent=case.get("evidence_consistent"),
        visual_confidence=float(case.get("visual_confidence") or 0.0),
        policy_threshold=float(case.get("policy_threshold") or 0.55),
        citations=tuple(case.get("citations") or ()),
        missing_evidence=tuple(case.get("missing_evidence") or ()),
        risk_signals=tuple(case.get("risk_signals") or ()),
    )


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    case_type = str(case["type"])
    expected = case.get("expected")
    details: dict[str, Any] = {}
    if case_type == "policy_gate":
        order = case.get("order") or {}
        knowledge = case.get("knowledge") or {}
        context = _review_context(order)
        hits = trusted_policy_hits(context, knowledge)
        facts = policy_facts(
            context,
            ToolResult(ok=True, name="retrieve_knowledge", data=knowledge),
        )
        actual: Any = bool(facts["trusted_policy_eligible"])
        details = {
            "trusted_hits": len(hits),
            "best_policy_score": best_policy_score(hits),
            "retrieval_mode": facts["retrieval_mode"],
            "policy_issues": list(facts["policy_issues"]),
        }
    elif case_type == "human_handoff":
        actual = is_explicit_human_request(
            str(case.get("message") or ""),
            case.get("recent_history") or [],
        )
    elif case_type == "http_trust_boundary":
        payload = build_langgraph_entry_payload(case.get("payload") or {})
        actual = {
            "source": payload["client_context"].get("source"),
            "allow_ai_review_submit": allow_ai_review_submit(payload),
        }
    elif case_type == "tool_http_error":
        status = int(case.get("status") or 0)
        actual = {
            "category": JavaToolClient._http_error_category(status),
            "retryable": status == 429 or status >= 500,
        }
    elif case_type == "decision_confidence":
        proposal = ReviewProposal(
            proposed_verdict="APPROVE",
            reason="evaluation",
            confidence=0.0,
            risk_reasons=(),
            assistant_reply="",
            model_confidence=float(case.get("model_confidence") or 0.0),
        )
        scored = apply_deterministic_confidence(proposal, _assessment(case))
        confidence = scored.confidence
        minimum, maximum = case.get("expected_range") or [0.0, 1.0]
        actual = confidence
        expected = {"min": minimum, "max": maximum}
        passed = float(minimum) <= confidence <= float(maximum)
        return _result(case, expected, actual, passed, {"confidence": confidence})
    else:
        raise ValueError(f"Unsupported evaluation case type: {case_type}")
    return _result(case, expected, actual, actual == expected, details)


def _result(
    case: dict[str, Any],
    expected: Any,
    actual: Any,
    passed: bool,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": case["id"],
        "type": case["type"],
        "description": case.get("description") or "",
        "expected": expected,
        "actual": actual,
        "passed": bool(passed),
        "details": details,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent 安全决策离线评测基线",
        "",
        f"- 数据集版本：`{report['dataset_version']}`",
        f"- 用例：{report['cases']}",
        f"- 通过率：{report['pass_rate']:.2%}",
        f"- 显式转人工召回率：{report['handoff_recall']:.2%}",
        f"- 自动审核安全违规：{report['auto_review_safety_violations']}",
        f"- 质量门禁：{'通过' if report['quality_gate_passed'] else '失败'}",
        "",
        "| 用例 | 类型 | 结果 | 说明 |",
        "|---|---|---:|---|",
    ]
    for row in report["results"]:
        lines.append(
            f"| `{row['id']}` | {row['type']} | {'通过' if row['passed'] else '失败'} | {row['description']} |"
        )
    lines.extend([
        "",
        "> 该评测只验证确定性安全护栏，不代表真实用户流量上的回答质量。真实模型、RAG 和视觉效果由独立基线评测覆盖。",
        "",
    ])
    return "\n".join(lines)
