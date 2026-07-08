# Human Service Evaluation API

This module is reserved for evaluating human customer service performance instead of AI or full-session satisfaction.

Base path:

```text
/api/merchant-cs/human-service-evaluation
```

## 1. Metric design

```http
GET /api/merchant-cs/human-service-evaluation/design
```

Purpose:
- Return the metric categories, weights, formulas and ownership.
- Help frontend build an admin page or help docs.

## 2. Submit user evaluation for a human agent

```http
POST /api/merchant-cs/human-service-evaluation/records
```

Request example:

```json
{
  "sessionId": 101,
  "humanAgentId": 1,
  "userId": 1001,
  "merchantCode": "MERCHANT_DEMO",
  "ratingOverall": 5,
  "ratingAttitude": 5,
  "ratingProfessional": 4,
  "ratingEfficiency": 4,
  "ratingResolution": 5,
  "cesScore": 4,
  "resolvedFlag": true,
  "firstContactResolvedFlag": true,
  "slaMetFlag": true,
  "firstHumanResponseSeconds": 42,
  "comment": "The human agent explained the process clearly.",
  "emotionBeforeHuman": "angry",
  "emotionAfterHuman": "anxious",
  "recontact72h": false,
  "reopened7d": false
}
```

## 3. Query evaluation by session

```http
GET /api/merchant-cs/human-service-evaluation/records/session/{sessionId}
```

Purpose:
- Query one human-service evaluation record for a session.

## 4. Submit QA review

```http
POST /api/merchant-cs/human-service-evaluation/records/{evaluationId}/qa-review
```

Request example:

```json
{
  "qaAttitudeScore": 5,
  "qaProfessionalScore": 4,
  "qaProcessScore": 4,
  "qaClosureScore": 5,
  "qaComment": "Good closure ownership and correct policy explanation.",
  "reviewerName": "qa_lead"
}
```

## 5. Agent overview

```http
GET /api/merchant-cs/human-service-evaluation/agents/{agentId}/overview?from=2026-07-01&to=2026-07-31
```

Key fields:
- `humanCsat`
- `cesAvg`
- `resolutionRate`
- `reopenRate`
- `firstContactResolutionRate`
- `qaScoreAvg`
- `emotionReliefRate`
- `finalScore`

## 6. Agent daily trend

```http
GET /api/merchant-cs/human-service-evaluation/agents/{agentId}/daily?from=2026-07-01&to=2026-07-07
```

Purpose:
- Support trend charting in the admin dashboard.

## 7. Reserved integration notes

Current state:
- This version reserves Spring Boot interfaces and scoring structure.
- The in-memory service can be replaced later by MyBatis + MySQL persistence.
- The final production logic should only count sessions with real human service.

Recommended production rules:
- Only evaluate sessions with `human_agent_id` not null.
- Separate logistics or warehouse root causes from directly controllable service quality.
- Use emotion change as a support signal instead of the dominant KPI.
- Avoid using NPS as a direct individual KPI for one human agent.
