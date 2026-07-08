# AI 辅助功能说明

> 架构边界见 [emotion-module-integration-guide.md](./emotion-module-integration-guide.md)：模型推理在 **Python Agent**，Java 只聚合 API 并落库。

客服会话详情页（`frontend/staff-auth-test-ui/src/views/SessionDetailView.vue`）集成三类 AI 能力。

## 使用前提

1. **Python Agent** 已启动：`http://127.0.0.1:8000/api/health` → `{"ok": true}`
2. **Spring Boot** 已启动：`http://127.0.0.1:8080/api`
3. 客服端 **真实接口**：`npm.cmd run dev:real`（mock 不走真实 AI）
4. 会话为 **人工模式（HUMAN）**，且有用户消息
5. （推荐）已配置 `DASHSCOPE_API_KEY` 与 pgvector，见情绪模块指南 §1–§3

## 功能一览

### 1. AI 提炼对话

**位置**：会话详情 → 右侧「AI 提炼对话」

| 字段 | 含义 | 示例 |
|------|------|------|
| 用户需求 | 用户想做什么 | 申请退款、要求补发 |
| 原因 | 为何提出该诉求 | 耳机没有声音，属于功能异常 |

**数据优先级**：

1. Qwen `conversation_understanding.user_need` / `normalized_issue` / `reason`
2. Agent `handoff_summary.problem` / `evidence`
3. 用户消息兜底（前端 + Java 双端）

**接口**：`GET /api/merchant-cs/sessions/{sessionId}/ai-assist`  
**Java**：`MerchantCsServiceImpl.buildConversationDigest()`  
**Python**：`qwen_service._conversation_understanding_system_prompt`

用户新消息经 WebSocket 触发 `reloadAssistAndMessages()` 自动刷新。

---

### 2. 一键回复

**位置**：输入框上方推荐条（填入 / 发送）

**链路**：

```text
GET /merchant-cs/sessions/{id}/ai-assist
  → MerchantCsServiceImpl.fetchAssistReply()
  → POST /api/agent/assist/reply（Spring 代理 Python）
  → QwenReturnService.handle() + RAG（pgvector）
  → data.recommendation.text
```

RAG 依赖 PostgreSQL/pgvector，未配置时会降级为 lexical fallback（见情绪模块指南排障）。

---

### 3. 情绪变化监控

对应架构三层中的 **Python 识别 → Java 落库 → 商家 UI 消费**（见情绪模块指南 §5）。

| 路径 | 说明 |
|------|------|
| 小程序发消息 | `UserChatController` → `ChatEmotionAnalysisService` |
| 客服加载消息 | `listSessionMessages()` → `backfillMissingEmotions()` |
| Agent 持久化 | `api_server._persist_user_messages()` |

**Python 接口**：`POST /api/analyze/emotion`（已实现，对应指南 §7 建议 tool）  
**Java 网关**：`AgentGatewayService.analyzeEmotion()`

落库字段：`chat_message.emotion_*`、`chat_session.emotion_*`

---

## 相关 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/merchant-cs/sessions/{id}/ai-assist` | AI 辅助聚合 |
| GET | `/api/merchant-cs/sessions/{id}/messages` | 消息（含情绪） |
| POST | `/api/agent/assist/reply` | 回复建议 |
| POST | `/api/analyze/emotion` | 单条情绪分析 |
| POST | `/api/agent/chat` | 用户端智能客服 |

## 关键代码

```text
src/.../MerchantCsServiceImpl.java          AI 辅助聚合
src/.../ChatEmotionAnalysisServiceImpl.java  情绪分析接入
python_agent/agents/emotion_agent.py         Qwen 情绪
python_agent/services/qwen_service.py        对话理解 + 回复
python_agent/api_server.py                   /analyze/emotion
```

## 常见问题

| 现象 | 处理 |
|------|------|
| AI 提炼为空 | 检查 8000/8080、`dev:real`、会话是否有用户消息 |
| 情绪仅首条有 | 打开会话会 backfill；需 Agent 正常；重启 Java + Python |
| 一键回复 502 | Agent 未启动或超时 |
| RAG 质量差 | 检查 `DASHSCOPE_API_KEY`、`PGVECTOR_DSN`（见情绪指南 §2） |

更多联调项见 [emotion-module-integration-guide.md §9](./emotion-module-integration-guide.md)。
