# 商家客服端与平台管理员端

> AI 能力在 **会话详情** 消费 Python Agent 结果，架构见 [emotion-module-integration-guide.md](./emotion-module-integration-guide.md) 与 [ai-assist-module-guide.md](./ai-assist-module-guide.md)。

工程：`frontend/staff-auth-test-ui`  
访问：`http://127.0.0.1:5173`

---

## 一、商家客服工作台

### 启动

```powershell
cd frontend/staff-auth-test-ui
npm.cmd install
npm.cmd run dev          # Mock，不连后端
npm.cmd run dev:real     # 真实联调（AI 必用）
```

### 登录

```text
账号：cs_demo  密码：123456  商家编码：MERCHANT_DEMO
```

### 路由

| 路由 | 功能 |
|------|------|
| `/dashboard` | 工作台 |
| `/sessions` | 在线会话（HUMAN） |
| `/sessions/:id` | 会话详情 + **AI 辅助** |
| `/tickets` | 售后工单 |
| `/orders` | 订单核验 |
| `/products` | 商品管理 |
| `/reviews` | 用户评价 |
| `/notices` | 通知 |
| `/profile` | 个人中心 |

### 会话详情 AI 能力

- **AI 提炼对话**：用户需求 + 原因
- **一键回复**：Qwen + RAG 推荐话术
- **情绪变化监控**：逐条用户消息 Qwen 情绪
- WebSocket：`ws://127.0.0.1:8080/api/ws/chat`

### API 前缀

`http://127.0.0.1:8080/api/merchant-cs/*`

详见 [merchant-customer-service-api.md](./merchant-customer-service-api.md)

---

## 二、平台管理员控制台

### 入口

登录页 → **管理员入口**，或 `/admin/login`

```text
账号：admin_demo  密码：123456
```

### 路由

| 路由 | 功能 |
|------|------|
| `/admin/dashboard` | 平台概览 |
| `/admin/accounts` | 客服账号治理 |
| `/admin/knowledge` | 知识库管理（对接 pgvector 同步） |

管理员负责 **账号 + 知识库**，不直接接待会话。知识库维护流程见 [emotion-module-integration-guide.md §3](./emotion-module-integration-guide.md)。

---

## 三、Mock vs 真实

| 项目 | `dev` | `dev:real` |
|------|-------|------------|
| 后端 | 否 | 8080 + 建议 8000 |
| AI 提炼/回复/情绪 | mock | Qwen + pgvector |
| 会话消息 | mock | MySQL + WS |

---

## 四、联调链路

```text
小程序 /chat/send
  → Java 情绪分析 → MySQL
  → WS → 客服端 SessionDetailView
  → GET /ai-assist → Python assist/reply
  → 展示提炼、一键回复、情绪趋势
```

总览：[module-integration-overview.md](./module-integration-overview.md)
