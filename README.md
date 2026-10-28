# Ecommerce After-Sales System

面向电商售后场景的智能客服与工单协同系统。项目覆盖用户咨询、售后申请、凭证审核、知识检索、AI 辅助决策、人工接管、商家运营和链路监控，并通过 Java 业务内核、Python LangGraph Agent、事件驱动架构与分层 RAG 保证业务状态可控、AI 结论可解释、分布式失败可恢复。

## 项目亮点

- **单 Agent + 渐进式 Skill 架构：** 按咨询、补证、正式审核和人工转接按需加载 Skill；正式审核由一张 LangGraph 图共享可信工单上下文，并行检索政策与审核凭证，汇合为一份评估，再由确定性 Gate 和 Java 状态机约束审核决策。
- **异步审核可靠性：** 基于 Transactional Outbox 解耦业务事务与 Kafka 发布，通过事件幂等键、Redis TTL 续期与超时接管处理重复消费和消费者崩溃；结合有限重试、DLQ 与人工审核降级，实现至少一次投递下的可恢复处理。
- **知识工程与 Agentic RAG：** 面向 PDF、Markdown 和 TXT 设计标题层级感知的结构化递归切片，保留段落、列表、表格和页码语义；基于 pgvector、pg_trgm 与 RRF 构建混合检索，在知识覆盖不足时生成最多 3 条互补 Query，执行一次有界并行重试与融合排序。
- **RAG 质量治理：** 构建覆盖检索、上下文、生成与业务路由的分层评测体系，结合数据契约校验定位链路质量损耗；[60 条样本的离线报告](docs/rag-optimization-report.md)记录了 Faithfulness 85.99%、Answer Relevancy 90.93% 和 True Hallucination Rate 5%。
- **全链路可观测：** 以 Trace ID 串联 Java、Outbox、Kafka、Agent 工具调用与结果落库，并通过 Prometheus + Grafana 监控请求、延迟、错误、RAG 降级、幂等处理、DLQ 和人工转接等关键指标。

## 一、总体架构

```mermaid
flowchart TB
    subgraph Client["交互层"]
        U["用户端<br/>uni-app / 微信小程序"]
        S["商家客服端<br/>Vue 3"]
        O["管理员端<br/>Vue 3"]
    end

    subgraph Java["业务层：Java Spring Boot"]
        API["REST API / WebSocket"]
        AUTH["认证、权限、商家隔离"]
        BIZ["订单、售后、会话、知识管理"]
        FSM["业务状态机与事务"]
        IAPI["Agent Internal APIs"]
        OUTBOX["Transactional Outbox"]
    end

    subgraph Agent["智能层：Python LangGraph"]
        CHAT["AfterSalesAgent<br/>唯一调度主体"]
        REVIEW["formal-review Skill<br/>单张正式审核图"]
        INPUT["输入校验 / 补证等待"]
        POLICY["政策检索节点"]
        EVIDENCE["凭证审核节点"]
        MERGE["review_synthesis<br/>单份评估与提案"]
        GATE["Deterministic Gate"]
        TOOL["受控工具注册表"]
    end

    subgraph Data["数据与基础设施"]
        MYSQL[("MySQL<br/>业务事实来源")]
        PG[("PostgreSQL + pgvector<br/>知识检索来源")]
        REDIS[("Redis<br/>幂等、缓存、限流")]
        KAFKA["Kafka<br/>异步审核事件"]
        MODEL["LLM / Embedding / Reranker / Vision"]
    end

    subgraph Observe["可观测性"]
        METRICS["Prometheus"]
        DASH["Grafana"]
        TRACE["Trace ID / 结构化日志"]
    end

    U --> API
    S --> API
    O --> API
    API --> AUTH --> BIZ --> FSM
    FSM --> MYSQL
    FSM --> OUTBOX --> KAFKA
    API --> CHAT
    KAFKA --> CHAT
    CHAT --> REVIEW
    REVIEW --> INPUT
    INPUT -->|完整| POLICY
    INPUT -->|完整| EVIDENCE
    INPUT -->|缺失| IAPI
    POLICY --> MERGE
    EVIDENCE --> MERGE
    MERGE --> GATE
    GATE --> IAPI
    POLICY --> PG
    POLICY --> MODEL
    EVIDENCE --> MODEL
    CHAT --> TOOL
    REVIEW --> TOOL
    TOOL --> IAPI --> BIZ
    Java --> REDIS
    Agent --> REDIS
    Java --> METRICS
    Agent --> METRICS
    METRICS --> DASH
    Java --> TRACE
    Agent --> TRACE
```

### 核心职责边界

| 模块 | 拥有的职责 | 明确不做 |
| --- | --- | --- |
| Java 业务服务 | 鉴权、权限、订单、售后工单、会话消息、事务、状态机、最终审核结果 | 不把业务状态交给模型直接修改 |
| Python Agent | LangGraph 编排、意图理解、工具规划、RAG、视觉审核、风险分析、回复生成 | 不直写 MySQL，不拥有最终业务状态 |
| 前端 | 用户交互、消息渲染、状态展示和失败时的短期交互兜底 | 不把本地状态当作会话或工单事实 |
| MySQL | 业务事实与审计记录 | 不保存向量检索运行状态 |
| PostgreSQL + pgvector | 已发布知识、Chunk、Embedding 和检索元数据 | 不保存订单、工单或聊天业务状态 |
| Redis | 消费幂等、短期状态、缓存和限流 | 不承担长期业务持久化 |
| Kafka | 事件投递、异步解耦和故障隔离 | 不作为业务最终状态来源 |

## 二、完整业务链路

```mermaid
flowchart TD
    START["用户进入商品、订单或售后入口"] --> RESOLVE["Java 解析用户、商家、订单、工单与 sessionId"]

    RESOLVE --> TYPE{"请求类型"}

    TYPE -->|普通咨询| MSG["Java 持久化用户消息"]
    MSG --> CHAT["会话 ReAct Agent"]
    CHAT --> CTX["读取订单、工单、会话与知识"]
    CTX --> REPLY["生成建议或触发人工接管"]
    REPLY --> SAVE["Java 持久化 AI / 系统消息"]
    SAVE --> SYNC["用户端与商家端按 sessionId 重载历史"]

    TYPE -->|提交售后| APPLY["Java 校验订单归属、申请条件与幂等"]
    APPLY --> TX["同一事务创建工单、会话快照与 Outbox"]
    TX --> MYSQL[("MySQL")]
    TX --> PUB["Outbox Publisher"]
    PUB --> KAFKA["Kafka Review Request"]
    KAFKA --> CLAIM["Redis event_id 幂等认领"]
    CLAIM --> REVIEW["AfterSalesAgent 调用单张正式审核图<br/>从 Java 读取可信工单上下文"]
    REVIEW --> INPUT{"问题描述与附件齐全？"}
    INPUT -->|否| MORE["Java 记录补证请求并暂停审核"]
    MORE --> RESUME["新凭证事件恢复后重读 Java 上下文"]
    RESUME --> INPUT
    INPUT -->|是| POLICY["政策检索节点"]
    INPUT -->|是| VISION["凭证审核节点"]
    POLICY --> MERGE["review_synthesis<br/>一份 ReviewAssessment + 提案"]
    VISION --> MERGE
    MERGE --> GATE{"确定性 Gate"}
    GATE -->|满足自动通过条件| APPROVE["提交 APPROVE 建议"]
    GATE -->|风险、不确定或失败| HUMAN["提交 MANUAL_REVIEW_REQUIRED"]
    APPROVE --> JAVA_APPLY["Java 校验 review_request_id 与证据版本"]
    HUMAN --> JAVA_APPLY
    JAVA_APPLY --> RESULT["MySQL 保存审核结果并更新会话快照"]
    MORE --> NOTICE["WebSocket / 历史消息通知两端"]
    RESULT --> NOTICE

    TYPE -->|商家处理| STAFF["Java 校验商家权限"]
    STAFF --> ACTION["回复会话、审核工单、管理订单商品"]
    ACTION --> STAFF_SAVE["Java 持久化操作结果"]
    STAFF_SAVE --> NOTICE
```

这条链路有两个关键约束：

1. 所有写操作最终回到 Java，由 Java 校验用户归属、商家权限、当前状态和幂等键。
2. 前端展示以 Java 持久化后的结果为准；发送消息后优先重新加载会话历史，而不是只在本地追加。

## 三、单 Agent 与能力分层

系统只有一个自主调度主体 `AfterSalesAgent`。聊天请求由它选择会话 Skill；类型明确的 Kafka 正式审核事件直接调用 `FormalReviewWorkflow`，不再执行一次 LLM 意图识别。正式审核的政策检索和凭证审核是图内节点，不是两个 Workflow 或独立 Agent。

| 组件 | 触发方式 | 目标 | 是否可直接形成业务结果 |
| --- | --- | --- | --- |
| AfterSalesAgent | HTTP 聊天或 Kafka 正式审核事件 | 识别聊天意图并调度 Skill；已知事件直接路由 | 否 |
| 正式审核 Skill | Kafka 售后审核事件 | 编排政策检索、凭证审核、复杂综合与 Gate | 否，只生成并提交建议 |
| 政策检索节点 | 正式审核工作流内并行执行 | 检索可信政策，判断政策覆盖与适用性 | 否，输出政策事实 |
| 凭证审核节点 | 正式审核工作流内并行执行 | 审核图片凭证，识别一致性、缺失项和风险 | 否，输出视觉事实 |
| `review_synthesis` | 并行节点汇合后执行 | 生成一份 `ReviewAssessment` 和审核提案 | 否 |
| 复杂案例综合调用 | `review_synthesis` 内按需触发 | 仅综合单份评估并生成复核提案 | 否，不能调用工具或绕过 Gate |
| Deterministic Gate | 并行节点汇合后执行 | 用确定性规则选择自动通过或人工审核建议 | 只选择提交动作，最终仍由 Java 落库 |

### 3.1 会话 ReAct Agent 子图

```mermaid
flowchart TD
    A0["receive_message<br/>标准化用户、会话、订单与工单上下文"] --> A1["classify_or_plan<br/>LLM Function Calling + 规则护栏"]
    A1 --> ROUTE{"route_after_plan"}

    ROUTE -->|调用工具| A2["tool_call<br/>校验工具名、参数、权限与重复调用"]
    ROUTE -->|需要人工| A6["human_handoff"]
    ROUTE -->|无需工具| A7["final_reply"]

    A2 --> A3["observe_tool_result<br/>统一 success / error_category / observation"]
    A3 --> A4["decide_next<br/>结合工具结果与最大步数判断下一步"]
    A4 --> NEXT{"route_after_decision"}

    NEXT -->|继续查询或执行| A2
    NEXT -->|失败、风险或不确定| A6
    NEXT -->|信息充分| A7

    A6 --> A7
    A7 --> END["END<br/>通过 Java append_chat_message 持久化"]
```

会话 Agent 的工具边界包括：

- 查询用户订单、订单详情、物流和已有售后工单
- 查询会话历史和售后知识
- 获取工单可信上下文
- 请求人工接管
- 通过 Java 追加聊天消息

工具执行被拆分为“调用—观察—决策”，便于统一处理超时、参数错误、权限拒绝、空结果和可恢复故障。循环受最大步数、重复工具调用检测和终态动作校验约束。

### 3.2 正式审核单工作流

```mermaid
flowchart TD
    A["load_trusted_context<br/>Java 可信工单上下文"] --> C{"上下文可用且状态可审核？"}
    C -->|否| MANUAL["submit_manual_review"]
    C -->|是| B{"validate_review_inputs<br/>描述和附件齐全？"}
    B -->|否| R["request_missing_evidence<br/>Java 记录补证请求"]
    R -->|已记录| WAIT["await_evidence<br/>等待新的凭证事件"]
    WAIT --> RELOAD["prepare_resumed_attempt<br/>清理本次评估状态"]
    RELOAD --> A
    R -->|失败| MANUAL
    R -->|证据版本已变化| STALE["结束本次事件"]
    B -->|是| PLAN["sop_plan<br/>确定性生成政策查询"]
    PLAN --> P["policy_review<br/>严格过滤；必要时最多改写一次"]
    PLAN --> V["visual_review<br/>审核同一上下文的附件"]
    P --> M["review_synthesis<br/>唯一 ReviewAssessment<br/>常规提案或按需复杂综合<br/>确定性置信度"]
    V --> M
    M --> G{"deterministic_gate"}
    G -->|条件满足| APPROVE["submit_review"]
    G -->|不可信、不确定或失败| MANUAL
    APPROVE --> JAVA["Java 校验请求 ID 和证据版本"]
    MANUAL --> JAVA
    JAVA -->|已应用| END["结束"]
    JAVA -->|旧版本或状态变化| STALE
```

补证只发生在输入校验阶段。补证事件恢复后重新读取 Java 上下文，再次校验输入；进入并行评估后，Gate 只选择自动通过或转人工。政策节点和视觉节点共享一份 `TrustedCaseContext`，各自只接收调用工具所需字段，不创建第二套业务上下文或子工作流。

政策节点以商家、政策版本、业务时间等可信字段严格过滤。覆盖不足且检索基础设施正常时，模型最多触发一次受限多查询改写，不能更改过滤条件。视觉节点只报告可见问题、凭证相关性、一致性与核验限制。两者汇合成唯一的 `ReviewAssessment`；复杂案例模型只提出 `ReviewProposal`，最终动作由确定性 Gate 选择。

模型输出必须通过 JSON 解析和字段校验；有限重试仍失败时转人工。Kafka 消费端在工作流外设置执行超时，超时后提交人工兜底，并标记在途工作取消；迟到的模型结果在调用 Java 前会被拦截。Java 对审核请求和证据版本执行条件更新，防止迟到或重复结果覆盖已持久化的审核状态。

`formal-review` 是唯一正式审核 Skill。它的 reference 仅约束同一工作流内的政策检索和凭证审核节点；Skill 名称与内容哈希版本进入 Trace 和 Java 审计字段。详细业务规则见 `docs/sop/formal-review-sop.md`。

## 四、异步审核、幂等与故障恢复

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant Java as Java 业务服务
    participant MySQL as MySQL
    participant Outbox as Outbox Publisher
    participant Kafka as Kafka
    participant Redis as Redis
    participant Agent as AfterSalesAgent
    participant Pg as pgvector
    participant Model as LLM / Vision
    participant Staff as 商家客服端

    User->>Java: 提交售后申请
    Java->>Java: 校验订单归属、状态与重复请求
    Java->>MySQL: 同一事务写入工单、消息、会话快照、Outbox
    Java-->>User: 立即返回工单已创建

    loop 定时发布 NEW / FAILED
        Outbox->>MySQL: 查询待发布事件
        Outbox->>Kafka: 以 review_request_id 为 Key 发布，事件包含 event_id
        Kafka-->>Outbox: 发布确认
        Outbox->>MySQL: 标记 PUBLISHED
    end

    Kafka->>Agent: after_sales.review.request
    Agent->>Redis: SET NX 认领 event_id
    alt 已完成的重复事件
        Redis-->>Agent: terminal + should_ack
        Agent->>Kafka: 提交 Offset
    else 正在处理
        Redis-->>Agent: PROCESSING
        Agent->>Kafka: 暂停分区并保留 Offset
    else 首次认领或过期接管
        Redis-->>Agent: claimed + attempt
        Agent->>Java: 查询最新可信工单上下文
        Java->>MySQL: 读取工单、订单、附件与版本
        Java-->>Agent: TrustedCaseContext
        alt 缺少问题描述或附件
            Agent->>Java: request_missing_evidence
            Java->>MySQL: 持久化补证请求与消息
            Java-->>Agent: 已应用或旧版本
            Agent->>Redis: 已应用则 EVIDENCE_REQUIRED；旧版本则释放 event_id
            Note over Agent,Java: 新凭证事件到达后沿用 review_request_id，重新读取 Java 上下文
        else 输入完整
            par policy_review
                Agent->>Pg: 严格过滤检索；必要时一次受限多查询
            and visual_review
                Agent->>Model: 视觉凭证审核
            end
            Agent->>Agent: 汇合为一份 ReviewAssessment
            opt 复杂且工具结果可用
                Agent->>Model: 受限综合生成 ReviewProposal
            end
            Agent->>Agent: 确定性置信度 + Gate
            alt 工作流在时限内完成
                Agent->>Java: 提交 APPROVE 或 MANUAL_REVIEW_REQUIRED
            else 模型或工作流超时
                Agent->>Agent: 标记在途执行取消
                Agent->>Java: 人工审核兜底
            end
            Java->>MySQL: 校验 review_request_id、证据版本与状态后条件更新
            Java-->>Agent: 已应用 / 旧版本 / 状态已变化
            Agent->>Redis: 已应用则记录终态；旧版本则释放 event_id
        end
        Agent->>Kafka: 提交 Offset
        Java-->>Staff: WebSocket / 会话刷新
    end
```

### 失败状态流

```mermaid
stateDiagram-v2
    [*] --> NEW: 事务写入 Outbox
    NEW --> PUBLISHED: Kafka 发布成功
    NEW --> FAILED: 发布失败
    FAILED --> PUBLISHED: 有限重试成功
    FAILED --> DEAD: 超过最大重试
    DEAD --> MANUAL_REQUIRED: Java 持久化人工审核兜底

    PUBLISHED --> PROCESSING: Redis 幂等认领
    PROCESSING --> COMPLETED: 审核结果成功落库
    PROCESSING --> EVIDENCE_REQUIRED: 已持久化补证请求
    PROCESSING --> MANUAL_REQUIRED: Agent 失败但人工兜底成功
    PROCESSING --> RELEASED: Java 拒绝旧审核或旧证据版本
    PROCESSING --> FAILED_CONSUME: Agent 与人工兜底均失败
    RELEASED --> [*]: 本次事件结束；新事件重新认领
    FAILED_CONSUME --> DLQ: 发布死信并提交 Offset
    DLQ --> MANUAL_REQUIRED: Java DLQ Consumer 幂等重放人工接管
```

可靠性策略：

- `review_request_id` 标识同一次审核生命周期，也是 Kafka Key 和 Java 条件更新参数；每次开始或补证恢复事件有独立的 `event_id`，用于 Outbox 和 Redis 消费幂等。Kafka 另行提交 Offset。
- Redis 使用带 TTL 的 `PROCESSING` 状态和心跳续期；崩溃后允许过期接管。
- 终态重复事件直接 ACK；仍在处理的重复事件不推进 Offset。
- Agent 异常先尝试通过 Java 持久化人工审核；只有人工兜底也失败才进入 DLQ。
- Java 返回旧审核或旧证据版本时，本次事件释放幂等占用并结束，由新事件重读工单，不在评估后回到补证节点。
- Outbox 发布耗尽重试时不能假装成功，必须把工单转入可见的人工处理状态。
- Trace ID 从 Java、Outbox、Kafka、Agent 工具调用一直贯穿到最终落库。

## 五、核心功能

### 用户侧

- 用户注册、登录、商品浏览、下单与订单查询
- 退款、退货等售后申请与处理进度跟踪
- 图片或文件形式的售后凭证上传与补充
- AI 与人工客服共享同一会话历史
- 售后状态、补证请求和人工接入通知同步展示

### 商家与管理员侧

- 按 `merchantCode` 隔离订单、商品、售后工单和会话
- 根据未回复状态、情绪风险、等待时间和最近活动生成队列优先级
- 统一渲染文本、图片和文件消息
- 展示 AI 建议、置信度、风险原因、证据缺口和审核轨迹
- 管理知识文档的草稿、发布、版本和检索元数据
- 查看 Agent 请求量、延迟、错误、降级、Outbox、DLQ 和人工转接指标

### AI 能力

- 意图识别、问题分类、情绪与风险分析
- 会话、订单、工单、商品与商家策略上下文组装
- 原生 Function Calling 与受控工具执行
- Agentic RAG 查询覆盖评估与多查询改写
- Dense、Keyword、RRF、Reranker 分层检索
- 图片凭证审核、风险识别与能力边界说明
- 单 Agent + Skills + Tools + Retrieval 的正式审核、复杂案例综合、确定性 Gate 与人工兜底
- 离线安全评测、正式审核链路评测和视觉基线评测

## 六、设计思想

1. **AI 辅助业务，不拥有业务**
   Agent 负责理解、检索、分析和建议；订单、工单、权限、事务和最终状态由 Java 控制。

2. **确定性规则约束概率模型**
   身份、金额、时效、状态机、可信政策资格、证据要求和自动审核条件写在代码中，模型输出不能绕过规则。

3. **最小上下文与最小工具权限**
   正式审核工作流只加载一份可信工单上下文，政策与视觉节点分别取调用工具必需的字段；复杂案例综合节点仅接收结构化评估，Agent 只能调用注册工具，不能直接访问业务数据库。

4. **事实来源唯一**
   MySQL 保存业务事实，pgvector 保存知识，Redis 保存短期控制状态，Kafka 传递事件，避免多份状态相互冲突。

5. **先持久化，再通知**
   工单、消息和审核结果先由 Java 事务落库，再通过 WebSocket 或历史重载同步给前端。

6. **异步解耦与幂等恢复**
   耗时 AI 审核不阻塞用户提交；Outbox、Kafka、Redis 和 Java 幂等共同处理重复投递与局部故障。

7. **失败时优先保证用户可继续**
   初始输入缺失时先补证并等待恢复；进入并行评估后，模型不确定、证据不足、政策不可信或外部服务异常均转人工，不再循环请求补证。

8. **检索质量优先于看似有答案**
   降级检索、Reranker 失败、政策版本不匹配或无可信引用时宁可拒绝自动审核，也不把低质量召回包装成确定结论。

9. **全链路可观测与可评测**
   节点耗时、工具结果、检索模式、置信度拆分、幂等状态、DLQ 和人工接管都有结构化记录和指标。

## 七、技术栈

| 层次 | 技术 |
| --- | --- |
| 业务后端 | Java 21、Spring Boot、MyBatis-Plus、Spring Security |
| AI 编排 | Python、LangGraph、LLM Function Calling |
| 模型能力 | DashScope LLM、text-embedding-v3、qwen3-rerank、视觉模型 |
| 知识检索 | PostgreSQL、pgvector、pg_trgm、RRF、Reranker |
| 数据与消息 | MySQL、Redis、Kafka、Transactional Outbox |
| 用户端 | uni-app、Vue 3、微信小程序 |
| 商家端 | Vue 3、Vite |
| 可观测性 | Prometheus、Grafana、Trace ID、结构化日志 |
| 部署 | Docker Compose |

## 八、项目结构

```text
.
├─ src/                         # Java 业务服务
├─ python_agent/                # Python LangGraph Agent
│  └─ after_sales_agent/
│     ├─ agent/workflows/       # 会话工作流与单张正式审核图
│     ├─ skills/                # 按需加载的 Skill 与节点参考约束
│     ├─ domain/                # 零框架依赖的业务类型
│     ├─ application/           # 对话、情绪与 RAG 查询用例
│     ├─ retrieval/             # pgvector、pg_trgm、RRF 与排序
│     ├─ providers/             # LLM、Embedding、Reranker 与 Vision
│     ├─ integrations/          # Java 内部 Agent API 网关
│     ├─ infrastructure/        # 幂等、指标、Trace 与 checkpoint
│     └─ interface/             # HTTP 与 Kafka 入口
├─ frontend/
│  ├─ uniapp/                   # 用户端小程序
│  └─ staff-auth-test-ui/       # 商家客服端与管理员端
├─ sql/                         # MySQL、pgvector 脚本与迁移
├─ observability/               # Prometheus / Grafana 配置
├─ tools/                       # 评测、审计和压测工具
├─ compose.yml                  # 本地完整链路编排
└─ Dockerfile                   # Java 服务镜像
```

## 九、快速启动

准备本地配置后，在仓库根目录运行：

```powershell
docker compose up -d --build
docker compose ps
```

主要地址：

- Java API：`http://127.0.0.1:8080/api`
- Java 健康检查：`http://127.0.0.1:8080/api/actuator/health`
- Python Agent：仅在 Compose 容器网络暴露 `8000`
- Grafana：按 `compose.yml` 的端口配置访问

用户端和商家端分别进入 `frontend/uniapp` 与 `frontend/staff-auth-test-ui` 安装依赖并启动。

## 十、配置安全

真实密钥、数据库密码和本机环境文件不应提交。项目通过环境变量或 Git 忽略的本地配置提供：

- Java 数据源、JWT、Kafka、Redis 和内部 Agent 鉴权配置
- Python LLM、视觉模型、Embedding、Reranker 与 pgvector 配置
- 前端不同环境的 API 地址
- Docker Compose 的本地变量

仓库只保留可公开的示例配置，运行日志、README 和提交记录不得输出真实凭据。
