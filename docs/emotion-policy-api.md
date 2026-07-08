# 情绪策略管理接口

这组接口用于给后续商家后台管理页预留接入能力，当前先提供稳定 API 骨架，不影响现有 `/api/agent/chat` 与 `/api/agent/review-images` 主流程。

基础路径：

```text
/api/merchant-cs/emotion-policy
```

## 1. 获取当前工作区

```http
GET /api/merchant-cs/emotion-policy/workspace
```

返回：

- `draft` 当前草稿
- `published` 当前已发布版本
- `versions` 历史版本列表

## 2. 保存草稿

```http
PUT /api/merchant-cs/emotion-policy/draft
```

请求示例：

```json
{
  "policyName": "耳机类情绪策略",
  "scopeType": "CATEGORY",
  "scopeValue": "earphone",
  "sensitivityLevel": "CUSTOM",
  "summary": "适合高客诉售后场景",
  "thresholds": {
    "anxious": 20,
    "dissatisfied": 45,
    "angry": 85
  },
  "weights": {
    "punctuationTriple": 8,
    "punctuationExclamation": 4,
    "punctuationQuestion": 4,
    "humanRequestFirst": 8,
    "humanRequestRepeat": 12,
    "timeout": 10,
    "merchantRejected": 12
  },
  "trend": {
    "consecutiveRiseTrigger": 2,
    "calmToAngryEnabled": true
  }
}
```

## 3. 发布策略

```http
POST /api/merchant-cs/emotion-policy/publish
```

## 4. 回滚版本

```http
POST /api/merchant-cs/emotion-policy/rollback
```

请求示例：

```json
{
  "targetVersion": 1,
  "rollbackReason": "新策略过于激进，回退到上一版"
}
```

## 5. 测试策略效果

```http
POST /api/merchant-cs/emotion-policy/test
```

请求示例：

```json
{
  "text": "你们到底什么时候处理，我已经催了三次了！！！",
  "historyTexts": [
    "怎么还没处理",
    "一直没人回复"
  ],
  "humanRequestCount": 2
}
```

返回重点字段：

- `emotionLabel` 当前情绪等级
- `score` 当前轮分值
- `trend` 情绪趋势
- `consecutiveRises` 连续上升次数
- `needHuman` 是否建议优先转人工
- `matchedRules` 命中的规则
- `escalationSignals` 升级信号
- `timeline` 每一轮时间序列结果
