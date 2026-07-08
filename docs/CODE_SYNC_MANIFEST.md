# 已同步代码清单

> 以下代码已从仓库根目录同步至本交付包（`1/ecommerce-after-sales-system-codex-test-ai-module-merge/`），与主工程保持一致。

## 后端 Java

| 模块 | 路径 |
|------|------|
| 情绪分析服务 | `src/main/java/.../service/ChatEmotionAnalysisService.java` |
| 情绪分析实现 | `src/main/java/.../service/impl/ChatEmotionAnalysisServiceImpl.java` |
| 客服 AI 辅助 | `src/main/java/.../service/impl/MerchantCsServiceImpl.java` |
| Agent 网关 | `src/main/java/.../service/impl/AgentGatewayServiceImpl.java` |
| 用户聊天 + 情绪落库 | `src/main/java/.../controller/UserChatController.java` |
| 微信沙盒登录 | `src/main/java/.../service/impl/UserAuthServiceImpl.java` |
| 沙盒用户初始化 | `src/main/java/.../config/WechatSandboxUserInitializer.java` |
| 小程序客户端配置 | `src/main/java/.../config/MiniappClientProperties.java` |
| WebSocket 情绪字段 | `src/main/java/.../dto/WsChatMessage.java` |
| Agent DTO | `src/main/java/.../dto/AgentGatewayDtos.java`（含 EmotionAnalyze） |
| 配置 | `src/main/resources/application.yml`（含 wechat-sandbox） |

## Python Agent

| 模块 | 路径 |
|------|------|
| 情绪分析 API | `python_agent/api_server.py` → `POST /api/analyze/emotion` |
| Qwen 对话理解 | `python_agent/after_sales_agent/services/qwen_service.py` |
| Qwen 情绪 | `python_agent/after_sales_agent/agents/emotion_agent.py` |

## 商家客服端 + 管理员端

| 模块 | 路径 |
|------|------|
| 会话详情 AI 辅助 UI | `frontend/staff-auth-test-ui/src/views/SessionDetailView.vue` |
| 客服 API / Mock | `frontend/staff-auth-test-ui/src/api/merchantCs.js` |
| 管理员控制台 | `frontend/staff-auth-test-ui/src/views/Admin*.vue` |
| 管理员 API | `frontend/staff-auth-test-ui/src/api/adminConsole.js` |
| 路由 | `frontend/staff-auth-test-ui/src/router/index.js` |

## 用户端小程序

| 模块 | 路径 |
|------|------|
| 登录页（微信沙盒） | `frontend/uniapp/src/pages/auth/auth.vue` |
| 沙盒登录工具 | `frontend/uniapp/src/utils/clientConfig.js` |
| API 基址 | `frontend/uniapp/src/utils/request.js` |

## 在本目录独立运行

```powershell
# 进入交付包根目录
cd 1\ecommerce-after-sales-system-codex-test-ai-module-merge

# 后端
..\..\mvnw.cmd spring-boot:run

# Python Agent
..\..\..\.venv\Scripts\python.exe python_agent\api_server.py

# 客服端
cd frontend\staff-auth-test-ui
npm.cmd run dev:real

# 小程序
cd frontend\uniapp
npm.cmd run build:mp-weixin
```

编译验证：`..\..\mvnw.cmd -DskipTests compile` → **BUILD SUCCESS**

## 同步方式

从主工程使用 `robocopy` 覆盖同步，避免嵌套目录。若主工程有更新，在仓库根目录执行：

```powershell
$root = "d:\ecommerce-after-sales-system-codex-test-ai-module-merge"
$dest = "$root\1\ecommerce-after-sales-system-codex-test-ai-module-merge"
robocopy "$root\src\main\java\com\ecommerce\aftersales\service" "$dest\src\main\java\com\ecommerce\aftersales\service" /E
robocopy "$root\src\main\java\com\ecommerce\aftersales\controller" "$dest\src\main\java\com\ecommerce\aftersales\controller" /E
robocopy "$root\src\main\java\com\ecommerce\aftersales\config" "$dest\src\main\java\com\ecommerce\aftersales\config" /E
robocopy "$root\src\main\java\com\ecommerce\aftersales\dto" "$dest\src\main\java\com\ecommerce\aftersales\dto" /E
robocopy "$root\src\main\java\com\ecommerce\aftersales\vo" "$dest\src\main\java\com\ecommerce\aftersales\vo" /E
robocopy "$root\python_agent" "$dest\python_agent" /E
robocopy "$root\frontend\uniapp\src" "$dest\frontend\uniapp\src" /E
robocopy "$root\frontend\staff-auth-test-ui\src" "$dest\frontend\staff-auth-test-ui\src" /E
Copy-Item "$root\src\main\resources\application.yml" "$dest\src\main\resources\application.yml" -Force
```
