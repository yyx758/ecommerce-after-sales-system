from __future__ import annotations

from after_sales_agent.agent.facts import (
    CaseContextBuilder,
    CaseFact,
    SourceKind,
    TrustLevel,
    facts_from_tool,
    trusted_policy_hits,
)

TRUSTED_KNOWLEDGE = {
    "mode": "hybrid_reranked",
    "filter_level": "strict",
    "reranker_succeeded": True,
    "trusted_policy_eligible": True,
    "hits": [
        {
            "source_type": "after_sales_policy",
            "trusted_policy_eligible": True,
            "relaxation_level": "strict",
            "rerank_score": 0.92,
            "snippet": "质量问题应提交可核验的问题凭证。",
            "citations": [{"source_code": "POLICY-001", "chunk_id": "chunk-001"}],
            "metadata": {"default_evidence": ["商品问题图片"]},
        }
    ],
}


def _relaxed_knowledge() -> dict:
    relaxed = {**TRUSTED_KNOWLEDGE, "filter_level": "relaxed"}
    return relaxed


def test_trusted_policy_hits_requires_every_filter() -> None:
    assert len(trusted_policy_hits(TRUSTED_KNOWLEDGE)) == 1
    assert trusted_policy_hits(_relaxed_knowledge()) == []
    assert trusted_policy_hits({**TRUSTED_KNOWLEDGE, "reranker_succeeded": False}) == []
    assert trusted_policy_hits({**TRUSTED_KNOWLEDGE, "trusted_policy_eligible": False}) == []
    assert trusted_policy_hits({"mode": "multi_query_rrf", "filter_level": "strict",
                                "trusted_policy_eligible": True, "reranker_succeeded": False,
                                "hits": TRUSTED_KNOWLEDGE["hits"]})


def test_hit_without_traceable_citation_is_not_trusted() -> None:
    knowledge = {**TRUSTED_KNOWLEDGE, "hits": [{**TRUSTED_KNOWLEDGE["hits"][0], "citations": []}]}

    assert trusted_policy_hits(knowledge) == []


def test_order_facts_carry_source_and_trust() -> None:
    facts = facts_from_tool("search_user_orders", [{
        "order_id": "99",
        "order_no": "SO-99",
        "status": "SHIPPED",
        "product_name": "蓝牙耳机",
        "category": "headphone",
        "merchant_code": "MERCHANT_DEMO",
        "create_time": "2026-07-01T10:00:00",
    }])

    status = next(fact for fact in facts if fact.claim_key == "order.status")
    assert status.value == "SHIPPED"
    assert status.trust == TrustLevel.VERIFIED
    assert status.source_kind == SourceKind.ORDER
    assert status.source_ref == "SO-99"
    assert status.observed_at.endswith("+00:00")


def test_policy_facts_only_record_trusted_hits() -> None:
    facts = facts_from_tool("retrieve_knowledge", TRUSTED_KNOWLEDGE)
    evidence = next(fact for fact in facts if fact.claim_key.startswith("policy.evidence."))

    assert evidence.trust == TrustLevel.REPORTED
    assert evidence.source_ref == "POLICY-001@chunk-001"

    relaxed_facts = facts_from_tool("retrieve_knowledge", _relaxed_knowledge())
    assert not [
        fact for fact in relaxed_facts
        if fact.claim_key.startswith("policy.evidence.")
    ]


def test_builder_reports_a_conflict_between_two_trusted_sources() -> None:
    builder = CaseContextBuilder()
    builder.add_tool_result("search_user_orders", [{"order_id": "99", "order_no": "SO-99", "status": "SHIPPED"}])
    builder.add_tool_result("get_order_detail", {"order_id": "99", "order_no": "SO-99", "status": "COMPLETED"})

    context = builder.build()

    assert [conflict.claim_key for conflict in context.conflicts] == ["order.status"]
    assert "存在来源冲突" in context.conflicts[0].describe()


def test_different_orders_do_not_conflict() -> None:
    builder = CaseContextBuilder()
    builder.add_tool_result("search_user_orders", [
        {"order_id": "99", "order_no": "SO-99", "status": "SHIPPED"},
        {"order_id": "100", "order_no": "SO-100", "status": "COMPLETED"},
    ])

    assert builder.build().conflicts == []


def test_builder_does_not_treat_a_user_claim_as_a_conflict() -> None:
    builder = CaseContextBuilder()
    builder.add_tool_result("search_user_orders", [{"order_id": "99", "order_no": "SO-99", "status": "SHIPPED"}])
    builder.add_facts([
        CaseFact(
            claim_key="order.status",
            value="已签收",
            trust=TrustLevel.CLAIMED,
            source_kind=SourceKind.USER,
            source_ref="user",
            comparable=False,
        )
    ])

    context = builder.build()

    assert context.conflicts == []


def test_builder_cross_checks_order_index_against_the_ticket_snapshot() -> None:
    builder = CaseContextBuilder()
    builder.add_tool_result("search_user_orders", [{
        "order_id": "99",
        "order_no": "SO-99",
        "existing_ticket_id": "500",
        "existing_ticket_status": "PENDING_REVIEW",
    }])
    builder.add_tool_result("get_after_sales_ticket", {
        "ticket_id": "500",
        "ticket_no": "T-500",
        "status": "APPROVED",
    })

    context = builder.build()

    assert [item.claim_key for item in context.discrepancies] == ["ticket.status"]
    assert "已核实为" in context.discrepancies[0].describe()


def test_render_lists_sources_and_conflicts() -> None:
    builder = CaseContextBuilder()
    builder.add_tool_result("search_user_orders", [{"order_id": "99", "order_no": "SO-99", "status": "SHIPPED"}])
    builder.add_unknown("适用政策版本未知")

    rendered = builder.build().render()

    assert "order.status" in rendered
    assert "可信等级 verified" in rendered
    assert "仍未知：适用政策版本未知" in rendered
