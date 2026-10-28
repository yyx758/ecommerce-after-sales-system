from __future__ import annotations

from after_sales_agent.tools import (
    READ_ONLY_TOOLS,
    ROLE_TOOL_NAMES,
    AgentToolRegistry,
    ToolRole,
)


def test_consultation_role_sees_only_read_only_tools() -> None:
    names = {spec["name"] for spec in AgentToolRegistry().tool_specs(ToolRole.CONSULTATION)}

    assert names == set(READ_ONLY_TOOLS)
    assert "submit_ai_review" not in names
    assert "append_chat_message" not in names
    assert "handoff_to_human" not in names
    assert "request_missing_evidence" not in names


def test_formal_review_role_may_submit_a_verdict() -> None:
    names = {spec["name"] for spec in AgentToolRegistry().tool_specs(ToolRole.FORMAL_REVIEW)}

    assert "submit_ai_review" in names
    assert names >= set(READ_ONLY_TOOLS)


def test_internal_multi_query_tool_is_never_exposed_to_a_model() -> None:
    registry = AgentToolRegistry()

    assert "retrieve_knowledge_multi" not in {spec["name"] for spec in registry.tool_specs()}
    assert "retrieve_knowledge_multi" in registry._internal_registry()


def test_every_tool_spec_declares_its_safety_metadata() -> None:
    for spec in AgentToolRegistry.all_tool_specs():
        assert spec["read_only"] in (True, False)
        assert spec["risk_level"] in {"low", "medium", "high"}
        assert spec["input_schema"]["additionalProperties"] is False


def test_role_lookup_is_explicit_about_unknown_roles() -> None:
    try:
        AgentToolRegistry().role_tool_names("not-a-role")
    except KeyError:
        return
    raise AssertionError("unknown role must be rejected")


def test_read_only_tools_are_declared_once() -> None:
    assert READ_ONLY_TOOLS <= ROLE_TOOL_NAMES[ToolRole.FORMAL_REVIEW]
    assert "submit_ai_review" not in READ_ONLY_TOOLS
