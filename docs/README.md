# 面试资料索引

## 当前实现版（优先阅读）

1. [当前实现面试复习手册](interview-review-current.md)：两分钟介绍、核心链路、可靠性、RAG、指标口径、高频追问和源码地图。
2. [项目根 README](../README.md)：当前完整架构图、Workflow 图与启动方式。
3. [后端性能实测](backend-performance-optimization-report-20260821.md)：本机压测与异步审核验证。
4. [RAG 最新单次全链路报告](../python_agent/evaluation/full_chain_report_rrf.md)：60 条数据集的可复算结果。
5. [Skill 渐进式加载报告](skill-progressive-loading-report-20260821.md)：加载策略与静态 Token 对比。
6. [上下文工程交付状态](context-engineering-implementation.md)：代码、灰度开关、迁移和已执行验证。

> 原 `docs/interview/` 手册已在最新架构整合时删除，下面的复习入口已改为当前代码基线，避免继续引用旧版多 Agent、旧目录或过期指标。

## 附录：Layered RAG 本地发布与回滚

Layered retrieval is disabled by default with `RAG_LAYERED_RETRIEVAL_ENABLED=false`. Set it to `true` only after the target environment has completed the PostgreSQL migration and backfill and the offline Holdout filter-violation gate is zero. This switch does not change Java ownership of knowledge lifecycle or publishing state.

### Configuration

For Docker Compose, create the project-level interpolation file and keep real credentials out of Git:

```powershell
Copy-Item .env.example .env
```

Compose reads shared rollout and Reranker values from this project-level `.env` (or from the invoking shell); it does not read those values from `python_agent/.env`. When starting the Python Agent directly, separately copy `python_agent/.env.example` to `python_agent/.env`.

- `PGVECTOR_DSN` is the PostgreSQL/pgvector connection string.
- `DASHSCOPE_API_KEY` (or `BAILIAN_API_KEY`) is required for `text-embedding-v3`; the running Agent process must receive it.
- Keep `RAG_LAYERED_RETRIEVAL_ENABLED=false` for compatibility until rollout gates pass.
- `KNOWLEDGE_MAX_FILE_BYTES=10485760` (10 MiB) is enforced by Java at the multipart and knowledge-service upload boundaries. The Agent does not receive raw knowledge files and does not enforce this setting.
- Leave `RERANK_PROVIDER`, `RERANK_BASE_URL`, and `RERANK_API_KEY` empty to disable external reranking. When enabled, retain `RERANK_TIMEOUT_SECONDS=3`, `RERANK_MAX_RETRIES=1`, and `RERANK_MAX_CANDIDATES=20`.

`compose.yml` passes the shared retrieval switch to Agent and Java. Validate its resolved settings without starting services:

```powershell
docker compose config
```

### Migration and startup

New Compose PostgreSQL volumes are initialized through `sql/pgvector_schema.sql`. For an existing volume, back up PostgreSQL first, then apply the additive migration. It does not drop tables or delete Drafts or historical Chunks.

```powershell
Get-Content .\sql\migrations\20260721_add_layered_rag_lifecycle.sql |
  docker compose exec -T postgres psql -U postgres -d after_sales_rag
docker compose up -d postgres mysql redis kafka agent java
docker compose ps
```

After startup, verify `postgres`, `agent`, and `java`, then run the minimum acceptance flow: a Markdown upload reaches `PROCESSING` then `REVIEW_REQUIRED`; editing a Draft increments its revision; a stale `expectedRevision` returns HTTP 409; and a successful publish goes through `PUBLISHING` to `PUBLISHED`. A retrieval must only use `chunk.revision = published_revision`. If a replacement embedding fails, the prior published revision must remain retrievable.

### Reranker degradation and troubleshooting

Reranker timeout, rate limiting, circuit breaking, or missing configuration should produce `mode=hybrid_rrf_degraded` and `trusted_policy_eligible=false`; degraded results must not drive trusted-policy automation.

`lexical_fallback_after_embedding_error` means the embedding call failed but PostgreSQL keyword fallback returned hits. It does not prove that the knowledge base is empty. Check, in order:

1. Whether the running Agent has `DASHSCOPE_API_KEY` or `BAILIAN_API_KEY`.
2. Whether `PGVECTOR_DSN` points at the intended database.
3. Whether `knowledge_document`, `knowledge_chunk`, and `published_revision` contain published data.
4. Embedding service reachability plus the model name and dimensions used at ingestion.

Common statuses or errors are `PARSE_FAILED`, `CLASSIFY_FAILED`, `EMBEDDING_FAILED`, `UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE_OR_MISSING`, and the publish-conflict HTTP 409. Preserve the error code and revision before retrying, requesting a corrected file, or handing off for review; do not manually move the published pointer.

### Rollback

Set `RAG_LAYERED_RETRIEVAL_ENABLED=false` in the runtime environment and restart Agent and Java to return to the compatibility retrieval path. Do not delete new tables, columns, Drafts, or historical Chunks. Stop new Java publishing operations and hide the Draft publishing entry point while keeping compatible list/detail fields readable. Re-enable only after migration, backfill, and offline safety gates are completed again.

Offline metrics must be reported with sample size, data distribution, annotation method, and runtime configuration. Small offline samples are not production recall claims, and this guide makes no 100% recall claim.

这里只保留后端 + AI Agent 面试需要的当前架构、源码入口和可核验的离线评测资料。内容以当前仓库代码为准，不把历史设计或小样本离线指标描述成线上生产效果。

## 专题深挖

1. [售后 Agent 总体架构](after-sales-agent-architecture.md)
2. [RAG Runtime Architecture](rag-runtime-architecture.md)
3. [Agent 可观测性与评测](agent-observability-and-evaluation.md)
4. [Agent 安全决策基线](agent-safety-baseline.md)
5. [正式审核 SOP](sop/formal-review-sop.md)
6. [Python Agent 代码结构](../python_agent/代码结构.md)

## 指标口径与证据

- [Agent 可观测性与评测说明](agent-observability-and-evaluation.md)
- [Agent 安全决策基线](agent-safety-baseline.md)
- [RAG 最新单次全链路结果](../python_agent/evaluation/full_chain_report_rrf.md)
- [情绪识别独立挑战集](emotion-priority-holdout.md)
- [视觉模型离线评测](视觉模型离线评测报告.md)

同目录的 JSON 文件是评测结果和复算输入，保留作为证据，不作为主要阅读入口。

## 两天复习建议

- 第一天：当前实现面试复习手册 → 根 README 架构图 → 对照源码地图追主链路。
- 第二天：专题深挖，重点练习 Outbox、Kafka ACK/offset、Redis 幂等、SQL 条件更新、RAG/视觉 Gate 和故障降级。
- 面试前：只复习当前手册中的“两分钟项目介绍”“高频追问”“容易说错的话”和“30 分钟复习顺序”。
