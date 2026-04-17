# Deployment Information

## Public URL

<https://web-production-1ef04.up.railway.app>

## Platform

Railway

---

## Test Commands

### Health Check

```bash
curl https://web-production-1ef04.up.railway.app/health
{"message":"AI Agent running on Railway!","docs":"/docs","health":"/health"}
```

### Readiness Check

```bash
curl https://web-production-1ef04.up.railway.app/ready
{"ready":true,"checks":{"app":true}}
```

### API Test (with authentication)

```bash
curl -X POST https://web-production-1ef04.up.railway.app/ask \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user", "question": "What is deployment?"}'
```

{"user_id":"test-user","question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","platform":"Railway"}

### Metrics (protected)

```bash
curl https://web-production-1ef04.up.railway.app/metrics \
  -H "X-API-Key: YOUR_AGENT_API_KEY"
```

{"uptime_seconds":503.9,"total_requests":2,"requests_by_key":{"YOUR_AGENT_API_KEY":2},"daily_spend_usd":0.0002,"daily_budget_usd":10.0,"budget_remaining_usd":9.9998,"rate_limit_per_minute":10,"redis_connected":false,"environment":"development","date":"2026-04-17"}

---

## Environment Variables Set

| Variable | Description |
|---|---|
| `PORT` | Port the server listens on (Railway injects automatically) |
| `REDIS_URL` | Redis connection string (Railway Redis plugin) |
| `AGENT_API_KEY` | Secret key clients must include as `X-API-Key` |
| `ENVIRONMENT` | `production` — disables `/docs` and strict-mode checks |
| `RATE_LIMIT_PER_MINUTE` | Max requests per API key per minute (default: 10) |
| `DAILY_BUDGET_USD` | Global daily LLM spend cap in USD (default: 10.0) |
| `LOG_LEVEL` | `INFO` in production |
| `OPENAI_API_KEY` | Optional — omit to use mock LLM |

---

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
