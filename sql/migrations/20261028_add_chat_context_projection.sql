-- Derived conversation continuity only. Orders, tickets and policy remain in their existing sources.
CREATE TABLE IF NOT EXISTS chat_context_projection (
    session_id BIGINT NOT NULL PRIMARY KEY,
    last_message_id BIGINT NOT NULL,
    goal_message_id BIGINT NULL,
    goal_text VARCHAR(500) NOT NULL DEFAULT '',
    goal_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_chat_context_projection_session FOREIGN KEY (session_id) REFERENCES chat_session(id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
