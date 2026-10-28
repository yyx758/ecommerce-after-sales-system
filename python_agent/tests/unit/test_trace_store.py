from __future__ import annotations

from after_sales_agent.infrastructure.trace_store import (
    TraceStore,
    build_trace_store_from_env,
)


def test_a_store_without_a_dsn_is_disabled_and_never_raises() -> None:
    store = TraceStore(dsn="", schema="agent_runtime")

    assert store.enabled is False
    store.persist({"trace": {"trace_id": "abc"}})
    store.close()


def test_the_store_is_built_from_the_review_checkpoint_database(monkeypatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_DSN", "postgresql://example/agent")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SCHEMA", "agent_runtime")
    monkeypatch.delenv("AGENT_TRACE_STORE_DSN", raising=False)
    monkeypatch.delenv("AGENT_TRACE_STORE_SCHEMA", raising=False)

    store = build_trace_store_from_env()

    assert store.enabled is True
    assert store.dsn == "postgresql://example/agent"
    store.close()


def test_the_store_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TRACE_STORE_ENABLED", "false")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_DSN", "postgresql://example/agent")

    store = build_trace_store_from_env()

    assert store.enabled is False
    store.close()


def test_an_invalid_schema_falls_back_to_the_default(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TRACE_STORE_ENABLED", "true")
    monkeypatch.setenv("AGENT_TRACE_STORE_DSN", "postgresql://example/agent")
    monkeypatch.setenv("AGENT_TRACE_STORE_SCHEMA", "not a schema!")

    store = build_trace_store_from_env()

    assert store.schema == "agent_runtime"
    store.close()


def test_a_full_queue_drops_traces_instead_of_blocking_the_request() -> None:
    store = TraceStore(dsn="postgresql://example/agent", schema="agent_runtime", max_queue=1)
    try:
        for index in range(5):
            store.persist({"trace": {"trace_id": f"trace-{index}"}})
        assert store.dropped >= 1
    finally:
        store.close()
