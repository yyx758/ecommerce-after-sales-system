# 售后 Agent 上下文工程交付状态

> 2026-10-28：用户要求直接启用，`AGENT_CONTEXT_MODE=active` 已改为默认值。真实模型成对质量门禁尚未完成，不能宣称输入 Token、延迟或审核质量已改善。

## 已接入的能力

| PRD 项 | 当前实现 |
| --- | --- |
| F1 工具投影 | `ContextProjector` 对订单、工单、商家策略、可信 RAG 和视觉结果按字段投影；对外 `tool_trace` 只给状态、引用和长度，不返回原始工具数据。事实账本记录来源引用、观测时间、工单指纹与证据版本；状态矛盾最多重查一次 Java，同版本矛盾或规划后变化转人工。 |
| F2 任务视图与预算 | `ContextAssembler` 保留当前消息、诉求来源、工单范围、必要事实、政策原文及引用；第二轮只补充新事实与安全关键事实。预算含系统提示、工具 Schema、消息、事实及观测，预留输出和安全余量；超限安全转人工。只在政策摘录已进入新视图时，成对移除过长的旧检索调用与返回。正式审核综合输入超限改为人工复核建议。 |
| F3 跨轮延续 | Java 为最近消息提供字符串消息 ID 与时间；MySQL `chat_context_projection` 保存可重建的当前诉求索引，较旧消息不能覆盖较新版本。用户补传时保留原诉求，明确新请求时更新诉求；证据引用从 Java 消息读取，订单/工单/政策事实每次重新核验。 |
| F4 差量与失效 | `ContextDiff` 记录新陈述、附件引用指纹、政策版本差异与冲突；本轮事实按版本处理。正式审核恢复后仍重读 Java 工单并重做政策、视觉评估，没有跨次复用旧审核结论。 |

## 配置与迁移

- 新建 MySQL 库使用 `sql/schema.sql`；已有库执行 `sql/migrations/20261028_add_chat_context_projection.sql`。PostgreSQL Agent 运行态执行 `sql/migrations/20261028_add_agent_trace_store.sql`。派生投影不可用时，Java 仍可从 `chat_message` 重建诉求，不阻断消息写入。
- `AGENT_CONTEXT_MODE=active|shadow|legacy`：`active` 让新视图驱动规划；`shadow` 构建新视图但使用原规划输入；`legacy` 回到旧规划输入。工具白名单投影与 Trace 脱敏在三个模式下均生效。
- `AGENT_CONTEXT_WINDOW_TOKENS=8192`、`AGENT_CONTEXT_SAFETY_TOKENS=2048` 是保守默认值；切换模型时应按模型实际上下文上限配置，并结合供应商 `usage` 校准估算。

## 已执行验证

- Python 全套：539 通过、4 跳过、4 deselected；Java 全套：149 个测试，0 失败、0 错误、28 跳过（本机测试报告）；Compose 配置校验通过。
- [100 条合成会话离线提示词契约报告](../python_agent/evaluation/context_projection_contract_report.json)：旧版与新视图两轮累计**估算**输入中位数分别为 4817、5016 Token。该数据不包含供应商真实使用量，也没有答案质量评分；当前样本没有显示 Token 节省。
- [1 条双模式真实模型烟测](../python_agent/evaluation/context_live_ab_report.json)：两模式均返回安全动作；只验证评测入口和供应商 `usage` 采集，不能据此推断总体质量、延迟或费用。首次普通沙箱尝试均连接超时，提权后成功获取模型响应。
- 已在本机 Compose MySQL 的 `ecommerce_aftersales` 执行 `20261028_add_chat_context_projection.sql`，并通过 `SHOW CREATE TABLE chat_context_projection` 核验主键、外键与字段。已在本机 PostgreSQL 的 `after_sales_rag` 执行 `20261028_add_agent_trace_store.sql`，并核验 `agent_runtime.agent_trace` 字段。
- 已重建并替换 Agent、Java、review-consumer 容器；Agent 容器内 `AGENT_CONTEXT_MODE=active`，Agent 健康检查返回 `ok=true`，Java 健康检查返回 `UP`，Prometheus 的 `ecommerce-java` target 为 `up`。
- 镜像构建依赖源改为“国内镜像优先、官方源回退”（`PIP_INDEX_URL`、`PIP_FALLBACK_INDEX_URL`、`MAVEN_MIRROR_URL` 三个 build-arg）。起因是直连 `files.pythonhosted.org` 下载 jieba 的 19MB sdist 被截断，pip 报 sha256 校验失败；同一份文件从国内镜像取得的 sha256 与官方一致。在 Linux 沙盒按 Dockerfile 同款命令装完全量依赖耗时 5.6 秒，并跑通 539 个 Python 测试；`docker compose build` 的回退逻辑用桩程序覆盖了“首选成功 / 首选失败回退 / 两者都失败必须构建失败”三种场景。
- **镜像重建与启动尚未由本次会话执行**：沙盒无法访问宿主机的 Docker Engine，只能在本机运行 `python tools/verify_docker_stack.py` 完成重建与验收（服务状态、健康检查、`AGENT_CONTEXT_MODE=active`、镜像内新模块、两张迁移表）。该脚本的判定逻辑已用桩程序验证。
- 首次在本机执行验收时，17/19 项通过，镜像构建与上下文相关检查全部通过；两项 Java 健康检查失败，特征为 `RemoteDisconnected`。原因是 Windows 上 Python 读取注册表系统代理后把 `127.0.0.1:8080` 也交给代理（`ProxyOverride` 默认 `<local>` 不覆盖 `127.0.0.1`）。脚本已改为显式绕过代理的 `ProxyHandler({})`，并新增 Compose 内网探针（从 agent 容器请求 `java:8080`）、冷启动重试与 Java 启动日志检查，区分"代理拦截""Java 未就绪""Java 启动失败"三种情况。

## 后续灰度门禁

已按用户要求直接启用 `active`。后续仍需按 [PRD](prd-agent-context-engineering.md) 对 100 条会话做三轮成对真实模型 A/B 与人工质量标注；若出现政策适用、关键事实、补证或安全动作回归，可立即设 `AGENT_CONTEXT_MODE=shadow` 并重启 Agent。未经评测不得宣称性能或质量收益。
