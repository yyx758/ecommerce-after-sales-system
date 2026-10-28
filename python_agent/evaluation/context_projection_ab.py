"""Paired offline prompt-contract benchmark; no model quality claim.

Runs 100 synthetic conversations through the legacy and new context assembly
with the same tool fixtures. Provider usage and answer quality require a
separate live A/B run before rollout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import median
import time
from typing import Any

from after_sales_agent.agent.facts import CaseContextBuilder
from after_sales_agent.agent.facts.models import CaseFact
from after_sales_agent.agent.workflows.consultation.context_assembler import ContextAssembler
from after_sales_agent.agent.workflows.consultation import ConsultationWorkflow
from after_sales_agent.agent.workflows.consultation.planner import ConsultationPlanner
from after_sales_agent.agent.workflows.consultation.prompts import (
    planner_system_prompt, planner_user_message,
)
from after_sales_agent.providers.llm_client import get_llm_client
from after_sales_agent.tools import ToolResult


SCENARIOS = (
    ("普通政策咨询", "{product}出现质量问题，可以申请退款吗？", "申请退款"),
    ("十轮长会话", "这次补充后，我的{product}退款申请进展如何？", "申请退款"),
    ("多订单核验", "我买了两件{product}，哪笔订单对应这次售后？", "核实售后订单"),
    ("政策版本变更", "商家政策更新后，{product}这单按哪个版本处理？", "确认适用政策"),
    ("模糊图片后补传", "之前的{product}图片模糊，现在补传清晰凭证。", "申请退款"),
    ("证据充分后陈述矛盾", "我之前说{product}坏了，现在发现可能没有坏。", "申请退款"),
    ("订单状态推进", "{product}订单之前待签收，现在签收了吗？", "查询订单状态"),
    ("同版本状态冲突", "同一工单的{product}审核状态显示不一致，请核实。", "查询售后状态"),
    ("模型超时兜底", "请帮我查{product}的售后进度。", "查询售后进度"),
    ("无效输出兜底", "请说明{product}退款需要哪些凭证。", "申请退款"),
)
PRODUCTS = ("耳机", "手机", "外套", "鞋子", "水杯", "台灯", "背包", "键盘", "行李箱", "相机")


def cases() -> list[dict[str, Any]]:
    result = []
    for scenario, message_template, goal in SCENARIOS:
        for index, product in enumerate(PRODUCTS):
            order_id = str(10000 + len(result))
            safe_action = (
                "manual_handoff" if scenario in {"同版本状态冲突", "模型超时兜底", "无效输出兜底"}
                else "reverify_policy" if scenario == "政策版本变更"
                else "clarify_conflict" if scenario == "证据充分后陈述矛盾"
                else "answer_with_sources"
            )
            result.append({
                "case_id": f"CTX-{len(result) + 1:03d}", "scenario": scenario,
                "expected_goal": goal, "expected_fact_keys": ["order.status"],
                "allowed_policy_citations": ["P@c1"],
                "expected_safe_action": safe_action,
                "evidence_gap": ["清晰问题凭证"] if scenario == "模糊图片后补传" else [],
                "payload": {
                    "message": message_template.format(product=product),
                    "order_id": order_id, "session_id": str(20000 + len(result)),
                    "recent_history": [
                        {"role": "user" if turn % 2 == 0 else "assistant",
                         "message_id": str(turn + 1),
                         "content": f"{product}售后第 {turn + 1} 轮：{goal}与处理进度。"}
                        for turn in range(10)
                    ],
                    "history_summary": {
                        "current_user_goal": goal,
                        "current_user_goal_message_id": "1",
                        "conversation_summary": f"此前已提出{goal}，待继续核验相关凭证或状态。",
                        "summary_through_message_id": "5",
                    },
                },
                "order_id": order_id,
            })
    return result


def run() -> dict[str, Any]:
    assembler = ContextAssembler()
    system = planner_system_prompt()
    schemas = ConsultationPlanner(llm=object()).model_tools
    rows = []
    for case in cases():
        payload = case["payload"]
        builder = CaseContextBuilder()
        builder.add_facts([CaseFact("order.status", "SIGNED", "verified", "order", case["order_id"])])
        first_context = builder.build()
        first_legacy = planner_user_message(payload, first_context, trusted_hit_count=0,
                                            tool_calls_made=0, plan_round=1)
        first_view = assembler.view(payload, first_context, round_no=1,
                                    resolved_order_id=case["order_id"])
        first_active, _, _ = assembler.prepare(
            system_prompt=system, tool_schemas=schemas, messages=[], view=first_view,
            metadata={"plan_round": 1, "tool_calls_made": 0, "trusted_policy_hit_count": 0},
        )
        builder.add_facts([CaseFact("policy.evidence.P@c1", "质量问题需可核验凭证。", "reported",
                                    "policy", "P@c1", detail="v1", comparable=False)])
        second_context = builder.build()
        assistant = {"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function",
                     "function": {"name": "retrieve_knowledge", "arguments": {"query": "退款政策"}}}]}
        observation = {"role": "tool", "tool_call_id": "call-1", "name": "retrieve_knowledge",
                       "content": json.dumps({"source_code": "P", "chunk_id": "c1",
                                              "quote": "质量问题需可核验凭证。"}, ensure_ascii=False)}
        legacy_messages = [first_legacy, assistant, observation,
                           planner_user_message(payload, second_context, trusted_hit_count=1,
                                                tool_calls_made=1, plan_round=2)]
        second_view = assembler.view(payload, second_context, round_no=2,
                                     resolved_order_id=case["order_id"],
                                     seen_fact_keys={("order.status", case["order_id"], repr("SIGNED"), "")})
        active_messages, _, _ = assembler.prepare(
            system_prompt=system, tool_schemas=schemas,
            messages=[*first_active, assistant, observation], view=second_view,
            metadata={"plan_round": 2, "tool_calls_made": 1, "trusted_policy_hit_count": 1},
        )
        legacy_tokens = assembler.estimate({"system": system, "tools": schemas,
                                            "messages": [first_legacy]}) + assembler.estimate(
            {"system": system, "tools": schemas, "messages": legacy_messages})
        active_tokens = assembler.estimate({"system": system, "tools": schemas,
                                            "messages": first_active}) + assembler.estimate(
            {"system": system, "tools": schemas, "messages": active_messages})
        assert first_view.current_goal["source_message_id"] == "1"
        assert any(fact["claim_key"] == "order.status" for fact in first_view.facts)
        assert second_view.policy_excerpts[0]["source_ref"] == "P@c1"
        assert {fact["claim_key"] for fact in second_view.facts} == {"order.status"}
        rows.append({"case_id": case["case_id"], "scenario": case["scenario"],
                     "expected_safe_action": case["expected_safe_action"],
                     "legacy_estimated_input_tokens": legacy_tokens,
                     "active_estimated_input_tokens": active_tokens})
    return {
        "kind": "offline_prompt_contract_only", "case_count": len(rows),
        "provider_usage_measured": False, "answer_quality_measured": False,
        "median_legacy_estimated_tokens": median(row["legacy_estimated_input_tokens"] for row in rows),
        "median_active_estimated_tokens": median(row["active_estimated_input_tokens"] for row in rows),
        "rows": rows,
    }


class FixtureTools:
    """One frozen business snapshot shared by legacy and active runs."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.calls: list[str] = []

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(name)
        order_id = self.case["order_id"]
        order = {"order_id": order_id, "order_no": f"SO-{order_id}",
                 "status": "SIGNED", "merchant_code": "MERCHANT_DEMO",
                 "category": "general", "product_name": "售后商品",
                 "create_time": "2026-10-01T10:00:00+08:00"}
        ticket = {"ticket_id": f"T-{order_id}", "order_id": order_id,
                  "status": "WAITING_EVIDENCE", "merchant_code": "MERCHANT_DEMO",
                  "category": "general", "policy_version": "v1",
                  "context_version": "snapshot-1", "evidence_revision": 1,
                  "after_sales_applied_at": "2026-10-02T10:00:00+08:00"}
        if name == "get_order_detail":
            data: Any = order
        elif name == "search_user_orders":
            data = [order]
        elif name in {"get_existing_after_sales", "get_after_sales_ticket"}:
            data = ticket
        elif name == "get_merchant_policy":
            data = {"merchant_code": "MERCHANT_DEMO", "catalog_version": "v1",
                    "service_policy": {"policy_code": "P", "policy_version": "v1"}}
        elif name == "retrieve_knowledge":
            data = {"mode": "hybrid_reranked", "filter_level": "strict",
                    "trusted_policy_eligible": True, "reranker_succeeded": True,
                    "hits": [{"source_type": "after_sales_policy",
                              "trusted_policy_eligible": True, "relaxation_level": "strict",
                              "policy_version": "v1", "snippet": "质量问题需要可核验的问题凭证。",
                              "metadata": {"default_evidence": ["问题凭证"]},
                              "citations": [{"source_code": "P", "chunk_id": "c1"}]}]}
        elif name == "review_images":
            data = {"success": True, "evidence_consistent": True, "confidence": 0.9,
                    "observed_issue_types": ["functional_issue"]}
        elif name in {"append_chat_message", "request_missing_evidence", "handoff_to_human"}:
            data = {"session_id": self.case["payload"]["session_id"], "message_id": "1"}
        else:
            return ToolResult(ok=False, name=name, error_category="fixture_tool_unknown")
        return ToolResult(ok=True, name=name, data=data)


class UsageMeter:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.input_tokens: list[int] = []

    def chat(self, messages: Any, tools: Any = None, **kwargs: Any) -> dict[str, Any]:
        response = self.delegate.chat(messages, tools=tools, **kwargs)
        usage = response.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        if prompt_tokens is not None:
            self.input_tokens.append(int(prompt_tokens))
        return response

    def generate_structured(self, **kwargs: Any) -> dict[str, Any]:
        return self.delegate.generate_structured(**kwargs)


def run_live(*, runs: int = 3, max_cases: int = 100) -> dict[str, Any]:
    """Actual paired model run. Explicit opt-in because it calls a paid provider."""
    client = get_llm_client()
    rows = []
    previous_mode = os.environ.get("AGENT_CONTEXT_MODE")
    try:
        for case in cases()[:max_cases]:
            for run_index in range(runs):
                for mode in ("legacy", "active"):
                    os.environ["AGENT_CONTEXT_MODE"] = mode
                    tools = FixtureTools(case)
                    metered = UsageMeter(client)
                    workflow = ConsultationWorkflow(tools=tools, llm=metered)
                    payload = {**case["payload"], "user_id": "7"}
                    started = time.perf_counter()
                    try:
                        result = workflow.handle(payload)
                        error = None
                    except Exception as exc:  # noqa: BLE001 - record paired failure
                        result = {}
                        error = exc.__class__.__name__
                    rows.append({
                        "case_id": case["case_id"], "scenario": case["scenario"],
                        "run": run_index + 1, "mode": mode,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "provider_input_tokens": sum(metered.input_tokens) if metered.input_tokens else None,
                        "provider_usage_calls": len(metered.input_tokens),
                        "tool_calls": tools.calls, "need_human": result.get("need_human"),
                        "citations": (result.get("raw") or {}).get("policy_citations") or [],
                        "handoff_reason": (result.get("raw") or {}).get("handoff_reason"),
                        "error": error,
                    })
    finally:
        if previous_mode is None:
            os.environ.pop("AGENT_CONTEXT_MODE", None)
        else:
            os.environ["AGENT_CONTEXT_MODE"] = previous_mode
    return {"kind": "live_paired_model_run", "case_count": min(max_cases, len(cases())),
            "runs_per_mode": runs, "answer_quality_human_review_required": True, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call the configured real model")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-cases", type=int, default=100)
    args = parser.parse_args()
    if args.runs < 1 or not 1 <= args.max_cases <= 100:
        parser.error("runs must be positive and max-cases must be 1..100")
    output = Path(__file__).with_name(
        "context_live_ab_report.json" if args.live else "context_projection_contract_report.json")
    report = run_live(runs=args.runs, max_cases=args.max_cases) if args.live else run()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False))
