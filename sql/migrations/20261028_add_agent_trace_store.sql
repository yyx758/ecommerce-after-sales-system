-- Agent Trace 落库表。
--
-- 与业务库（MySQL）不同，Agent 运行时的 trace 与 LangGraph checkpointer 同属
-- Postgres agent_runtime schema：它们都是 Agent 的运行态数据，同一个 DSN
-- 一起配置，一起运维。应用侧在写入前会自行确保 schema 与表存在，因此本迁移
-- 是幂等的声明式补充。

CREATE SCHEMA IF NOT EXISTS agent_runtime;

CREATE TABLE IF NOT EXISTS agent_runtime.agent_trace
(
    id                BIGSERIAL    NOT NULL,
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
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_agent_trace_created_at
    ON agent_runtime.agent_trace (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_trace_trace_id
    ON agent_runtime.agent_trace (trace_id);
