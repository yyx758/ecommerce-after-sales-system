-- Human customer service evaluation design
-- This script only reserves schema and can be applied later when the main flow is connected.

CREATE TABLE IF NOT EXISTS service_evaluation
(
    id                           BIGINT       NOT NULL COMMENT 'Evaluation ID',
    session_id                   BIGINT       NOT NULL COMMENT 'Related chat session ID',
    human_agent_id               BIGINT       NOT NULL COMMENT 'Assigned human agent ID',
    user_id                      BIGINT       NULL     COMMENT 'User ID',
    merchant_code                VARCHAR(64)  NULL     COMMENT 'Merchant code',
    rating_overall               TINYINT      NULL     COMMENT 'Overall rating 1~5',
    rating_attitude              TINYINT      NULL     COMMENT 'Attitude rating 1~5',
    rating_professional          TINYINT      NULL     COMMENT 'Professional rating 1~5',
    rating_efficiency            TINYINT      NULL     COMMENT 'Efficiency rating 1~5',
    rating_resolution            TINYINT      NULL     COMMENT 'Resolution rating 1~5',
    ces_score                    TINYINT      NULL     COMMENT 'Customer effort score 1~5',
    resolved_flag                TINYINT      NOT NULL DEFAULT 0 COMMENT 'Whether issue is resolved',
    first_contact_resolved_flag  TINYINT      NOT NULL DEFAULT 0 COMMENT 'Whether resolved in one manual contact round',
    sla_met_flag                 TINYINT      NOT NULL DEFAULT 0 COMMENT 'Whether SLA target is met',
    first_human_response_seconds INT          NULL     COMMENT 'Seconds from assignment to first human response',
    comment                      VARCHAR(1000) NULL    COMMENT 'User comment',
    emotion_before_human         VARCHAR(20)  NULL     COMMENT 'Emotion before human service',
    emotion_after_human          VARCHAR(20)  NULL     COMMENT 'Emotion after human service',
    emotion_delta                INT          NULL     COMMENT 'Emotion relief delta, positive means better',
    recontact_72h                TINYINT      NOT NULL DEFAULT 0 COMMENT 'Whether user recontacts within 72h',
    reopened_7d                  TINYINT      NOT NULL DEFAULT 0 COMMENT 'Whether issue reopens within 7d',
    qa_attitude_score            TINYINT      NULL     COMMENT 'QA attitude score 1~5',
    qa_professional_score        TINYINT      NULL     COMMENT 'QA professional score 1~5',
    qa_process_score             TINYINT      NULL     COMMENT 'QA process score 1~5',
    qa_closure_score             TINYINT      NULL     COMMENT 'QA closure score 1~5',
    qa_comment                   VARCHAR(1000) NULL    COMMENT 'QA review comment',
    reviewer_name                VARCHAR(100) NULL     COMMENT 'QA reviewer name',
    result_layer_score           DECIMAL(5,2) NULL     COMMENT 'Result layer score 0~100',
    process_layer_score          DECIMAL(5,2) NULL     COMMENT 'Process layer score 0~100',
    quality_layer_score          DECIMAL(5,2) NULL     COMMENT 'Quality layer score 0~100',
    emotion_layer_score          DECIMAL(5,2) NULL     COMMENT 'Emotion layer score 0~100',
    final_service_score          DECIMAL(5,2) NULL     COMMENT 'Final human service score 0~100',
    status                       VARCHAR(20)  NOT NULL DEFAULT 'USER_SUBMITTED' COMMENT 'USER_SUBMITTED/QA_REVIEWED',
    deleted                      TINYINT      NOT NULL DEFAULT 0 COMMENT 'Logical delete',
    create_time                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Create time',
    update_time                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
    PRIMARY KEY (id),
    UNIQUE KEY uk_service_evaluation_session (session_id),
    INDEX idx_service_evaluation_agent_time (human_agent_id, create_time),
    INDEX idx_service_evaluation_final_score (final_service_score)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Human customer service evaluation table';

CREATE TABLE IF NOT EXISTS agent_service_metric_daily
(
    id                           BIGINT       NOT NULL COMMENT 'Daily metric ID',
    stat_date                    DATE         NOT NULL COMMENT 'Statistic date',
    human_agent_id               BIGINT       NOT NULL COMMENT 'Human agent ID',
    merchant_code                VARCHAR(64)  NULL     COMMENT 'Merchant code',
    sample_size                  INT          NOT NULL DEFAULT 0 COMMENT 'Evaluation sample count',
    human_csat                   DECIMAL(5,2) NULL     COMMENT 'Human CSAT 0~100',
    ces_avg                      DECIMAL(5,2) NULL     COMMENT 'CES average 0~100',
    resolution_rate              DECIMAL(5,2) NULL     COMMENT 'Resolution rate 0~100',
    reopen_rate                  DECIMAL(5,2) NULL     COMMENT 'Reopen rate 0~100',
    first_contact_resolution_rate DECIMAL(5,2) NULL    COMMENT 'FCR rate 0~100',
    qa_score_avg                 DECIMAL(5,2) NULL     COMMENT 'QA average score 0~100',
    emotion_relief_rate          DECIMAL(5,2) NULL     COMMENT 'Emotion relief rate 0~100',
    final_score                  DECIMAL(5,2) NULL     COMMENT 'Final score 0~100',
    create_time                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Create time',
    update_time                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
    PRIMARY KEY (id),
    UNIQUE KEY uk_agent_metric_daily (stat_date, human_agent_id),
    INDEX idx_agent_metric_daily_agent (human_agent_id, stat_date)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Daily metrics for human customer service';
