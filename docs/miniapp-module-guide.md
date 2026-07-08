# 用户端小程序说明

> 小程序只请求 **Java Spring Boot**（`/api/*`），不直连 Python Agent。AI/情绪由 Java 转发 Agent 处理。

工程路径：`frontend/uniapp`  
技术栈：Vue3 + UniApp（微信小程序）

## 功能列表

| 模块 | 页面 | 说明 |
|------|------|------|
| 登录 / 注册 / 找回密码 | `pages/auth/auth` | 手机号；微信沙盒一键登录；模拟扫码 |
| 首页 | `pages/home/home` | 入口导航 |
| 商品与购买 | 商品页 | 演示购买、生成订单 |
| 订单 | 列表 / 详情 | 订单状态 |
| 售后 | 申请 / 列表 / 详情 | 售后工单 |
| 在线咨询 | 聊天页 | AI 预接待 → 转人工 → 客服端可见 |

## 后端地址

`frontend/uniapp/src/utils/request.js`：

```js
export const BASE_URL = 'http://127.0.0.1:8080/api'
```

- 模拟器：`127.0.0.1`
- 真机：改为电脑局域网 IP
- 开发者工具：**不校验合法域名、web-view、TLS**

## 编译与导入

```powershell
cd frontend/uniapp
npm.cmd install
npm.cmd run build:mp-weixin
```

导入：`frontend/uniapp/dist/build/mp-weixin`（不要用 `dist/dev`）

## 登录

| 方式 | 说明 |
|------|------|
| 手机号 | `13800138000` / `123456` |
| 微信沙盒 | 一键登录或模拟扫码，无需 AppID |
| 接口 | `POST /api/miniapp/auth/wechat/login` |

## 咨询与转人工

```text
POST /api/chat/send
  → AI 预接待（关键词 mock）
  → 用户说「转人工」→ mode=HUMAN
  → Java 调用 Python 情绪分析 → 写入 chat_message
  → 客服端在线会话可见
```

## 主要 API

| 方法 | 路径 |
|------|------|
| POST | `/api/miniapp/auth/login` |
| POST | `/api/miniapp/auth/wechat/login` |
| GET | `/api/miniapp/public/client-config` |
| POST | `/api/chat/session` |
| POST | `/api/chat/send` |
| GET | `/api/chat/history` |

详见 [miniapp-user-auth-api.md](./miniapp-user-auth-api.md)

## 与整体架构的关系

```text
UniApp → Java /api/chat/*
         → Java → Python /analyze/emotion（情绪）
         → Java → Python /chat（完整 AI 对话，用户端 Agent 入口 /api/agent/*）
```

情绪与 AI 边界见 [emotion-module-integration-guide.md](./emotion-module-integration-guide.md)。

## 常见问题

- **`clientConfig.js` 未定义**：重新 `build:mp-weixin`，清微信缓存
- **登录 500**：确认 Spring Boot 最新进程、MySQL、`openid` 字段
- **连不上后端**：合法域名开关、局域网 IP、`0.0.0.0` 监听
