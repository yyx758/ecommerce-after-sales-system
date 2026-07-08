# 模块整合总览（AI 辅助 / 小程序 / 客服与管理端）

本说明位于交付目录：

```text
1/ecommerce-after-sales-system-codex-test-ai-module-merge/
```

与架构边界以 [emotion-module-integration-guide.md](./emotion-module-integration-guide.md) 为准。

## 架构分层（必读）

| 层 | 职责 | 技术 |
|----|------|------|
| Java Spring Boot | 业务 API、鉴权、订单/售后/会话/通知、状态硬校验 | MySQL |
| Python Agent | LLM、对话理解、情绪识别、RAG、图片理解、回复生成 | Qwen + LangGraph |
| PostgreSQL/pgvector | AI 知识库向量检索 | text-embedding-v3 |
| 前端 | 小程序用户端、商家客服端、平台管理员端 | UniApp + Vue3 |

**边界要求**（摘自情绪模块指南）：

- Java **不**直接调用 LLM，不定义 Agent tools。
- 情绪、提炼、一键回复的 **模型推理在 Python**；Java 聚合结果并落库。
- RAG 主库在 PostgreSQL，不要恢复旧 MySQL 情绪知识表作主库。

## 文档索引

| 文档 | 内容 |
|------|------|
| [emotion-module-integration-guide.md](./emotion-module-integration-guide.md) | pgvector、DashScope、情绪三层接入、边界与联调清单 |
| [ai-assist-module-guide.md](./ai-assist-module-guide.md) | 客服端 AI 提炼、一键回复、情绪监控 |
| [miniapp-module-guide.md](./miniapp-module-guide.md) | 用户端小程序 |
| [merchant-admin-module-guide.md](./merchant-admin-module-guide.md) | 商家客服工作台 + 平台管理员端 |

## 推荐启动顺序

```text
MySQL（3306）
  → PostgreSQL/pgvector（5432，RAG 可选但 AI 回复质量依赖）
  → Python Agent（8000，需 DASHSCOPE_API_KEY）
  → Spring Boot（8080）
  → 客服/管理端（5173，dev:real）
  → 微信小程序（开发者工具）
```

## 端口一览

| 服务 | 地址 |
|------|------|
| Spring Boot | `http://127.0.0.1:8080/api` |
| Python Agent | `http://127.0.0.1:8000/api` |
| 客服 / 管理端 | `http://127.0.0.1:5173` |
| 小程序 | 导入 `frontend/uniapp/dist/build/mp-weixin` |

## 默认演示账号

| 角色 | 账号 | 密码 | 入口 |
|------|------|------|------|
| 商家客服 | `cs_demo` | `123456` | `/login` |
| 平台管理员 | `admin_demo` | `123456` | 登录页 → 管理员入口 |
| 小程序用户 | `13800138000` | `123456` | 小程序登录 |
| 微信沙盒 | 一键登录 / 模拟扫码 | — | 无需真实 AppID |

商家编码：`MERCHANT_DEMO`

## 端到端数据流

```text
用户在小程序发消息
  → Java POST /chat/send
  → Java 调用 Python POST /analyze/emotion（Qwen 情绪）
  → 写入 chat_message / chat_session 情绪字段
  → WebSocket 推送客服端
  → 客服打开会话 GET /merchant-cs/sessions/{id}/ai-assist
  → Java 调用 Python POST /assist/reply（提炼 + 一键回复）
  → 客服端展示 AI 提炼、推荐回复、情绪趋势
```

## 快速启动（Windows）

详见 [emotion-module-integration-guide.md §4](./emotion-module-integration-guide.md) 与各模块指南。

```powershell
# 在项目根目录 1/ecommerce-after-sales-system-codex-test-ai-module-merge/ 下执行

# Python Agent
$env:DASHSCOPE_API_KEY=[Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY','User')
$env:PGVECTOR_DSN='postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag'
.\.venv\Scripts\python.exe python_agent\api_server.py

# Spring Boot（新终端）
.\mvnw.cmd spring-boot:run

# 客服端真实联调（新终端）
cd frontend\staff-auth-test-ui
npm.cmd run dev:real

# 小程序（新终端）
cd frontend\uniapp
npm.cmd run build:mp-weixin
```
