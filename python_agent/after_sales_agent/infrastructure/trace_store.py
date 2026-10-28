"""Agent Trace 落库。

之前 trace 只存在进程内的 120 条 deque 里，重启即丢，离线评测无法回放真实
流量。这里把它落到 Postgres（与 LangGraph checkpointer 同一个库），并且：

* **不阻塞主链路**——写入走后台线程 + 有界队列；
* **失败不影响返回**——落库异常只记日志，绝不把错误抛给请求方；
* **默认关闭**——没有配置 DSN 时是 no-op，不会在本地开发时误连生产库。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import queue
import re
import threading
from typing import Any

logger = logging.getLogger("after_sales_agent.trace_store")

_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {schema}.agent_trace (
    id                BIGSERIAL PRIMARY KEY,
    trace_id          VARCHAR(64)  NOT NULL,
    request_type      VARCHAR(64)  NOT NULL DEFAULT '',
    path              VARCHAR(128) NOT NULL DEFAULT '',
    order_id          VARCHAR(64)  NOT NULL DEFAULT '',
    session_id        BIGINT       NULL,
    reply_preview     VARCHAR(200) NOT NULL DEFAULT '',
    total_duration_ms INT          NOT NULL DEFAULT 0,
    step_count        INT          NOT NULL DEFAULT 0,
    tool_call_count   INT          NOT NULL DEFAULT 0,
    payload           JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_trace_created_at
    ON {schema}.agent_trace (created_at DESC)
"""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class TraceStore:
    """A background writer that keeps agent traces in Postgres."""

    dsn: str = ""
    schema: str = "agent_runtime"
    max_queue: int = 256

    def __post_init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=max(1, self.max_queue)
        )
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._connection: Any | None = None
        self._dropped = 0
        self._enabled = bool(self.dsn.strip()) and bool(
            _SCHEMA_PATTERN.fullmatch(self.schema)
        )
        if not self._enabled:
            logger.info("agent_trace_store disabled: no usable dsn or schema")
            return
        self._worker = threading.Thread(
            target=self._run,
            name="agent-trace-store",
            daemon=True,
        )
        self._worker.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def dropped(self) -> int:
        """How many traces were dropped because the queue was full."""
        return self._dropped

    def persist(self, event: dict[str, Any]) -> None:
        """Queue one trace event. Never raises."""
        if not self._enabled or self._worker is None:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1
            logger.warning("agent_trace_store queue full: trace dropped")

    def close(self) -> None:
        """Stop the worker after draining what is already queued."""
        if self._worker is None:
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=5)
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:  # noqa: BLE001 - shutdown must not raise
                    logger.exception("agent_trace_store connection close failed")
                self._connection = None

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            try:
                self._write(event)
            except Exception:  # noqa: BLE001 - persistence must never break the request
                logger.exception("agent_trace_store write failed")

    def _write(self, event: dict[str, Any]) -> None:
        connection = self._connect()
        if connection is None:
            return
        trace = event.get("trace") if isinstance(event.get("trace"), dict) else {}
        steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
        payload = {
            "event": event,
            "steps": steps,
        }
        connection.execute(
            f"INSERT INTO {self.schema}.agent_trace ("
            "trace_id, request_type, path, order_id, session_id, reply_preview,"
            "total_duration_ms, step_count, tool_call_count, payload"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
            (
                str(trace.get("trace_id") or event.get("trace_id") or ""),
                str(trace.get("request_type") or ""),
                str(event.get("path") or ""),
                str(event.get("order_id") or ""),
                event.get("session_id"),
                str(event.get("reply_preview") or "")[:200],
                int(trace.get("total_duration_ms") or 0),
                len(steps),
                _tool_call_count(steps),
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )

    def _connect(self) -> Any:
        with self._lock:
            if self._connection is not None:
                return self._connection
        try:
            import psycopg
        except ImportError:
            logger.warning("agent_trace_store requires psycopg; persistence disabled")
            return None
        try:
            connection = psycopg.connect(
                self.dsn,
                autocommit=True,
                prepare_threshold=0,
            )
            connection.execute(
                f"CREATE SCHEMA IF NOT EXISTS {self.schema}"
            )
            connection.execute(_CREATE_TABLE.format(schema=self.schema))
            connection.execute(_CREATE_INDEX.format(schema=self.schema))
        except Exception:  # noqa: BLE001 - a broken store must not break the request
            logger.exception("agent_trace_store connection failed")
            return None
        with self._lock:
            self._connection = connection
        return connection


def _tool_call_count(steps: list[Any]) -> int:
    """Count the tool invocations recorded in a trace."""
    total = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or "")
        if "tool" in name or name in {"consultation_plan"}:
            total += 1
    return total


def build_trace_store_from_env() -> TraceStore:
    """Build the trace store from the environment.

    The store reuses the review checkpoint database by default: agent runtime
    state and agent traces belong together, and one DSN is one thing to
    configure.
    """
    if not _env_bool("AGENT_TRACE_STORE_ENABLED", True):
        return TraceStore(dsn="", schema="agent_runtime")
    dsn = os.getenv("AGENT_TRACE_STORE_DSN", "").strip() or os.getenv(
        "LANGGRAPH_CHECKPOINT_DSN", ""
    ).strip()
    schema = (
        os.getenv("AGENT_TRACE_STORE_SCHEMA", "").strip()
        or os.getenv("LANGGRAPH_CHECKPOINT_SCHEMA", "agent_runtime").strip()
    )
    if not _SCHEMA_PATTERN.fullmatch(schema):
        schema = "agent_runtime"
    max_queue = int(os.getenv("AGENT_TRACE_STORE_MAX_QUEUE", "256") or 256)
    return TraceStore(dsn=dsn, schema=schema, max_queue=max_queue)


#: The process-wide store. It is a no-op until a DSN is configured.
TRACE_STORE = build_trace_store_from_env()
