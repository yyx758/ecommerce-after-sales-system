-- 售后规则引擎升级脚本（V1）
-- 目标：
-- 1. 在现有商品/政策/规则/工单表上补齐商家化、多类目、多商品售后规则能力
-- 2. 保持向后兼容，不删除现有字段
-- 3. 先以 JSON 字段承载复杂规则，便于 SpringBoot 后续实现 PolicyResolver

-- ============================================================
-- 1. 商家主表
-- ============================================================
CREATE TABLE IF NOT EXISTS merchant_info
(
    id                     BIGINT       NOT NULL COMMENT '商家ID',
    merchant_code          VARCHAR(64)  NOT NULL COMMENT '商家编码',
    merchant_name          VARCHAR(200) NOT NULL COMMENT '商家名称',
    contact_name           VARCHAR(100) NULL     COMMENT '联系人',
    contact_phone          VARCHAR(32)  NULL     COMMENT '联系电话',
    default_policy_version INT          NOT NULL DEFAULT 1 COMMENT '默认政策版本',
    status                 TINYINT      NOT NULL DEFAULT 1 COMMENT '状态：1启用，0停用',
    deleted                TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_merchant_code (merchant_code),
    INDEX idx_merchant_status (status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '商家信息表';

-- ============================================================
-- 2. 商品表扩展：增加商家、规则标签
-- ============================================================
ALTER TABLE product_info
    ADD COLUMN merchant_id BIGINT NULL COMMENT '所属商家ID' AFTER id,
    ADD COLUMN store_id BIGINT NULL COMMENT '所属店铺ID(预留)' AFTER merchant_id,
    ADD COLUMN category_code VARCHAR(100) NULL COMMENT '标准类目编码' AFTER category,
    ADD COLUMN sub_category_code VARCHAR(100) NULL COMMENT '二级类目编码' AFTER category_code,
    ADD COLUMN after_sales_tags JSON NULL COMMENT '售后标签(JSON数组，如[\"FRESH\",\"HIGH_VALUE\"])' AFTER sub_category_code,
    ADD COLUMN rule_profile_code VARCHAR(64) NULL COMMENT '规则模板编码' AFTER after_sales_tags;

ALTER TABLE product_info
    ADD INDEX idx_product_info_merchant (merchant_id),
    ADD INDEX idx_product_info_category_code (category_code),
    ADD INDEX idx_product_info_rule_profile_code (rule_profile_code);

-- ============================================================
-- 3. 售后政策表扩展：增加作用域
-- ============================================================
ALTER TABLE after_sales_policy
    ADD COLUMN scope_level VARCHAR(20) NOT NULL DEFAULT 'PLATFORM' COMMENT '作用域：PLATFORM/CATEGORY/MERCHANT/PRODUCT/SKU' AFTER policy_code,
    ADD COLUMN merchant_id BIGINT NULL COMMENT '适用商家ID' AFTER scope_level,
    ADD COLUMN store_id BIGINT NULL COMMENT '适用店铺ID(预留)' AFTER merchant_id,
    ADD COLUMN product_id BIGINT NULL COMMENT '适用商品ID' AFTER store_id,
    ADD COLUMN sku_id BIGINT NULL COMMENT '适用SKU ID(预留)' AFTER product_id,
    ADD COLUMN scene_code VARCHAR(50) NULL COMMENT '适用场景编码，如NO_REASON/QUALITY/FRESH_SPOILAGE' AFTER product_category,
    ADD COLUMN is_legal_baseline TINYINT NOT NULL DEFAULT 0 COMMENT '是否法律基线：1是，0否' AFTER summary,
    ADD COLUMN effective_time DATETIME NULL COMMENT '生效时间' AFTER expire_date,
    ADD COLUMN expire_time DATETIME NULL COMMENT '失效时间' AFTER effective_time;

ALTER TABLE after_sales_policy
    ADD INDEX idx_asp_scope (scope_level, merchant_id, product_id, sku_id),
    ADD INDEX idx_asp_scene_status (scene_code, status),
    ADD INDEX idx_asp_effective_time (effective_time, expire_time);

-- ============================================================
-- 4. 售后规则表扩展：增加作用域、JSON 规则块
-- ============================================================
ALTER TABLE after_sales_rule
    ADD COLUMN scope_level VARCHAR(20) NOT NULL DEFAULT 'PLATFORM' COMMENT '作用域：PLATFORM/CATEGORY/MERCHANT/PRODUCT/SKU' AFTER rule_code,
    ADD COLUMN merchant_id BIGINT NULL COMMENT '适用商家ID' AFTER scope_level,
    ADD COLUMN store_id BIGINT NULL COMMENT '适用店铺ID(预留)' AFTER merchant_id,
    ADD COLUMN product_id BIGINT NULL COMMENT '适用商品ID' AFTER store_id,
    ADD COLUMN sku_id BIGINT NULL COMMENT '适用SKU ID(预留)' AFTER product_id,
    ADD COLUMN scene_code VARCHAR(50) NULL COMMENT '售后场景编码，如NO_REASON/QUALITY/DAMAGE/FRESH_SPOILAGE' AFTER product_category,
    ADD COLUMN merge_mode VARCHAR(20) NOT NULL DEFAULT 'MERGE' COMMENT '规则合并方式：MERGE/REPLACE' AFTER scene_code,
    ADD COLUMN condition_json JSON NULL COMMENT '条件规则(JSON)' AFTER priority,
    ADD COLUMN action_json JSON NULL COMMENT '动作规则(JSON)' AFTER condition_json,
    ADD COLUMN evidence_json JSON NULL COMMENT '证据要求(JSON)' AFTER action_json,
    ADD COLUMN audit_json JSON NULL COMMENT '审核策略(JSON)' AFTER evidence_json,
    ADD COLUMN settlement_json JSON NULL COMMENT '费用/赔付策略(JSON)' AFTER audit_json,
    ADD COLUMN version INT NOT NULL DEFAULT 1 COMMENT '规则版本号' AFTER settlement_json,
    ADD COLUMN effective_time DATETIME NULL COMMENT '生效时间' AFTER version,
    ADD COLUMN expire_time DATETIME NULL COMMENT '失效时间' AFTER effective_time;

ALTER TABLE after_sales_rule
    ADD INDEX idx_asr_scene_status (scene_code, status),
    ADD INDEX idx_asr_scope (scope_level, merchant_id, product_id, sku_id),
    ADD INDEX idx_asr_category (product_category),
    ADD INDEX idx_asr_effective_time (effective_time, expire_time),
    ADD INDEX idx_asr_priority (priority);

-- ============================================================
-- 5. 工单表扩展：固化命中的规则快照
-- ============================================================
ALTER TABLE after_sales_ticket
    ADD COLUMN merchant_id BIGINT NULL COMMENT '所属商家ID' AFTER user_id,
    ADD COLUMN product_id BIGINT NULL COMMENT '商品ID' AFTER merchant_id,
    ADD COLUMN sku_id BIGINT NULL COMMENT 'SKU ID(预留)' AFTER product_id,
    ADD COLUMN matched_rule_id BIGINT NULL COMMENT '命中规则ID' AFTER aiRecommendType,
    ADD COLUMN matched_rule_version INT NULL COMMENT '命中规则版本号' AFTER matched_rule_id,
    ADD COLUMN policy_snapshot_json JSON NULL COMMENT '规则快照(JSON)' AFTER matched_rule_version,
    ADD COLUMN rule_trace_json JSON NULL COMMENT '规则解析链路(JSON)' AFTER policy_snapshot_json;

ALTER TABLE after_sales_ticket
    ADD INDEX idx_ast_merchant (merchant_id),
    ADD INDEX idx_ast_product (product_id),
    ADD INDEX idx_ast_rule (matched_rule_id, matched_rule_version);

-- ============================================================
-- 6. 规则示例数据：平台 / 类目 / 商家
-- ============================================================
INSERT INTO merchant_info (id, merchant_code, merchant_name, contact_name, contact_phone, default_policy_version, status, deleted)
VALUES
    (1001, 'MERCHANT_DIGITAL_A', '数码优选店', '张经理', '13800000001', 1, 1, 0),
    (1002, 'MERCHANT_CLOTHING_A', '服饰精选店', '李经理', '13800000002', 1, 1, 0),
    (1003, 'MERCHANT_FRESH_A', '生鲜直达店', '王经理', '13800000003', 1, 1, 0)
ON DUPLICATE KEY UPDATE
    merchant_name = VALUES(merchant_name),
    contact_name = VALUES(contact_name),
    contact_phone = VALUES(contact_phone),
    default_policy_version = VALUES(default_policy_version),
    status = VALUES(status),
    deleted = VALUES(deleted);

INSERT INTO after_sales_policy (
    id, policy_name, policy_code, scope_level, product_category, scene_code, content, summary,
    is_legal_baseline, status, version, deleted
)
VALUES
    (9001, '平台服饰七天无理由说明', 'POLICY_CLOTHING_7DAY', 'CATEGORY', 'CLOTHING', 'NO_REASON',
     '服饰类商品在不影响二次销售前提下可支持七天无理由退货，具体以商品完好、吊牌完整、未洗涤未穿着为准。',
     '服饰类一般支持七天无理由，需保持商品完好。', 0, 1, 1, 0),
    (9002, '平台生鲜售后说明', 'POLICY_FRESH_LIMIT', 'CATEGORY', 'FRESH', 'FRESH_SPOILAGE',
     '生鲜类商品通常不适用七天无理由退货，针对腐烂、变质、破损、少件等问题处理。',
     '生鲜类通常不支持无理由，支持坏果/腐烂/少件售后。', 0, 1, 1, 0),
    (9003, '平台数码功能故障说明', 'POLICY_DIGITAL_QUALITY', 'CATEGORY', 'DIGITAL', 'FUNCTION_FAULT',
     '数码类商品发生质量问题或功能故障时，可按商家规则支持退换修处理。',
     '数码类质量问题可按规则退换修。', 0, 1, 1, 0)
ON DUPLICATE KEY UPDATE
    policy_name = VALUES(policy_name),
    content = VALUES(content),
    summary = VALUES(summary),
    status = VALUES(status),
    version = VALUES(version);

INSERT INTO after_sales_rule (
    id, rule_name, rule_code, scope_level, merchant_id, product_category, scene_code,
    time_limit_days, freight_payer, audit_mode, priority, status, deleted,
    condition_json, action_json, evidence_json, audit_json, settlement_json, version
)
VALUES
    (
        8001, '服饰类七天无理由默认规则', 'RULE_CLOTHING_NO_REASON', 'CATEGORY', NULL, 'CLOTHING', 'NO_REASON',
        7, 'BUYER', 'MANUAL', 100, 1, 0,
        JSON_OBJECT(
            'receive_within_days', 7,
            'allow_opened', true,
            'need_tags_intact', true,
            'need_original_package', false,
            'need_washed', false
        ),
        JSON_OBJECT(
            'support_refund_only', false,
            'support_return_refund', true,
            'support_exchange', false,
            'support_repair', false,
            'support_partial_refund', false
        ),
        JSON_OBJECT(
            'need_problem_desc', true,
            'need_damage_photo', false,
            'need_outer_package_photo', false,
            'need_logistics_label_photo', false
        ),
        JSON_OBJECT(
            'audit_mode', 'MANUAL',
            'dispatch_to', 'AFTER_SALES_TEAM',
            'risk_level', 'NORMAL'
        ),
        JSON_OBJECT(
            'freight_payer', 'BUYER',
            'refund_ratio', 'FULL'
        ),
        1
    ),
    (
        8002, '生鲜腐烂坏果规则', 'RULE_FRESH_SPOILAGE', 'CATEGORY', NULL, 'FRESH', 'FRESH_SPOILAGE',
        NULL, 'SELLER', 'MANUAL', 120, 1, 0,
        JSON_OBJECT(
            'report_within_hours', 24,
            'allow_opened', true,
            'need_original_package', true
        ),
        JSON_OBJECT(
            'support_refund_only', true,
            'support_return_refund', false,
            'support_exchange', false,
            'support_repair', false,
            'support_partial_refund', true
        ),
        JSON_OBJECT(
            'need_problem_desc', true,
            'need_damage_photo', true,
            'need_outer_package_photo', true,
            'need_logistics_label_photo', true
        ),
        JSON_OBJECT(
            'audit_mode', 'MANUAL',
            'dispatch_to', 'FRESH_TEAM',
            'risk_level', 'HIGH'
        ),
        JSON_OBJECT(
            'freight_payer', 'SELLER',
            'refund_ratio', 'PARTIAL_OR_FULL'
        ),
        1
    ),
    (
        8003, '数码商家仅质量问题退货规则', 'RULE_DIGITAL_QUALITY_ONLY_M1001', 'MERCHANT', 1001, 'DIGITAL', 'NO_REASON',
        7, 'BUYER', 'MANUAL', 220, 1, 0,
        JSON_OBJECT(
            'receive_within_days', 7,
            'allow_opened', false
        ),
        JSON_OBJECT(
            'support_refund_only', false,
            'support_return_refund', false,
            'support_exchange', false,
            'support_repair', false,
            'support_partial_refund', false
        ),
        JSON_OBJECT(
            'need_problem_desc', false
        ),
        JSON_OBJECT(
            'audit_mode', 'MANUAL',
            'dispatch_to', 'DIGITAL_TEAM',
            'risk_level', 'NORMAL'
        ),
        JSON_OBJECT(
            'freight_payer', 'BUYER'
        ),
        1
    ),
    (
        8004, '数码商家功能故障规则', 'RULE_DIGITAL_FUNCTION_M1001', 'MERCHANT', 1001, 'DIGITAL', 'FUNCTION_FAULT',
        15, 'SELLER', 'MANUAL', 230, 1, 0,
        JSON_OBJECT(
            'receive_within_days', 15,
            'allow_opened', true,
            'need_serial_number', true
        ),
        JSON_OBJECT(
            'support_refund_only', true,
            'support_return_refund', true,
            'support_exchange', true,
            'support_repair', true,
            'support_partial_refund', false
        ),
        JSON_OBJECT(
            'need_problem_desc', true,
            'need_damage_photo', false,
            'need_fault_video', true,
            'need_serial_number', true
        ),
        JSON_OBJECT(
            'audit_mode', 'MANUAL',
            'dispatch_to', 'QUALITY_TEAM',
            'risk_level', 'HIGH'
        ),
        JSON_OBJECT(
            'freight_payer', 'SELLER',
            'refund_ratio', 'FULL'
        ),
        1
    )
ON DUPLICATE KEY UPDATE
    rule_name = VALUES(rule_name),
    scope_level = VALUES(scope_level),
    merchant_id = VALUES(merchant_id),
    product_category = VALUES(product_category),
    scene_code = VALUES(scene_code),
    time_limit_days = VALUES(time_limit_days),
    freight_payer = VALUES(freight_payer),
    audit_mode = VALUES(audit_mode),
    priority = VALUES(priority),
    status = VALUES(status),
    deleted = VALUES(deleted),
    condition_json = VALUES(condition_json),
    action_json = VALUES(action_json),
    evidence_json = VALUES(evidence_json),
    audit_json = VALUES(audit_json),
    settlement_json = VALUES(settlement_json),
    version = VALUES(version);
