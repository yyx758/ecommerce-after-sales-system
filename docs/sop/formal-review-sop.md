# 正式售后审核 SOP

## 目标与边界

本 SOP 规范 Kafka 触发的正式售后初审。AI 负责检索、观察、结构化评估和建议，不拥有订单、工单、权限、事务或最终业务状态。Java/MySQL 始终是业务事实来源。

Skill 定义位于 `python_agent/after_sales_agent/skills/formal-review/`，可执行 LangGraph 位于 `python_agent/after_sales_agent/agent/workflows/formal_review/`。文档描述业务意图，代码和自动化测试保证线上执行。

## 输入

- `review_request_id`：单次审核生命周期的幂等标识。
- Java 返回的最新工单、订单、附件、政策版本、证据版本和 `context_version`。
- Kafka 事件仅用于触发，不覆盖 Java 返回的业务事实。

## 标准流程

1. 从 Java 加载可信工单上下文；查询失败或工单状态已变化时转人工。
2. 校验问题描述和图片附件；缺失时请求补证并等待同一审核流程恢复。
3. 正式审核 Skill 确定性生成政策检索问题，不调用 LLM 规划路由。
4. 单个 LangGraph 从同一可信上下文并行执行政策检索节点和凭证审核节点，汇合后生成一份 `ReviewAssessment`。
5. 上下文版本不一致时直接转人工。
6. 评估复杂度：常规案例生成确定性提案；复杂案例进入受限综合节点。
7. 对提案应用确定性置信度模型和 Gate；评估完成后只提交审核或转人工，不再请求补证。
8. 通过 Java 内部接口提交建议，由 Java 再次校验并持久化。

## 升级条件

满足以下任一条件时，可进入复杂案例综合节点，但该节点不能调用工具、修改状态或绕过 Gate：

- 政策检索失败、降级、缺少引用、版本不匹配或无法形成可信政策。
- 视觉凭证不可核验、置信度不足、互相矛盾或存在风险信号。
- 可信政策要求的核心凭证仍无法确认。
- 政策与视觉事实存在需要语义综合的不确定性。

工具失败和上下文版本冲突必须失败关闭；无论综合节点输出什么，最终动作仍由 Gate 决定。

## Gate 决策

| 条件 | 动作 |
| --- | --- |
| 输入缺少问题描述或附件 | `REQUEST_EVIDENCE` |
| Skill 失败、证据风险、版本冲突或政策不可信 | `MANUAL_REVIEW` |
| 视觉不可核验或确定性置信度低于阈值 | `MANUAL_REVIEW` |
| 自动审核开启，政策可信，证据可核验且一致，确定性置信度达标 | `SUBMIT_REVIEW` |
| 其他未覆盖情况 | `MANUAL_REVIEW` |

## Skill 契约

- `formal-review` 是唯一正式审核 Skill。
- 政策检索和凭证审核是同一工作流中的并行节点，汇合后只生成一份 `ReviewAssessment`。
- Skill 名称和内容哈希版本必须进入 Trace 与 Java 审计字段 `skill_versions`。
- Skill 不得执行写操作，不得输出最终业务状态，不得包含某个截图或单品专用规则。

## 恢复与审计

- 补证恢复必须沿用同一 `review_request_id`，并重新加载 Java 上下文。
- 提交时携带预期证据版本；Java 返回 `STALE_EVIDENCE` 时结束本次评估并释放事件幂等占用，由新的凭证事件重新触发审核。
- Trace 必须记录 Skill 名称、版本、审核模式、升级原因、Gate 原因和最终 Java 返回。
