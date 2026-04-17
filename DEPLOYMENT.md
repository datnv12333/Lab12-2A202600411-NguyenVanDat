# Deployment Information

## Public URL

<https://ai-agent-production-production-83c0.up.railway.app>

## Platform

Railway

---

## Test Commands

### Health Check

```bash
curl https://ai-agent-production-production-83c0.up.railway.app/health
{"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":1125.4,"llm":"mock","redis_connected":false,"timestamp":"2026-04-17T15:53:34.274185+00:00"}
```

### Readiness Check

```bash
curl https://ai-agent-production-production-83c0.up.railway.app/ready
{"ready":true}
```

### API Test (with authentication)

```bash
curl -X POST https://ai-agent-production-production-83c0.up.railway.app/ask \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user", "question": "What is deployment?"}'
```

{"user_id":"test-user","question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","model":"gpt-4o-mini","history_length":4,"timestamp":"2026-04-17T16:02:33.050899+00:00"}

### Metrics (protected)

```bash
curl https://ai-agent-production-production-83c0.up.railway.app/metrics \
  -H "X-API-Key: YOUR_AGENT_API_KEY"
```

{"uptime_seconds":1670.4,"total_requests":14,"error_count":0,"rate_limit":{"requests_in_window":0,"limit":10,"remaining":10,"backend":"memory"},"daily_spend_usd":0.0,"daily_budget_usd":50.0,"redis_connected":false,"environment":"production","date":"2026-04-17"}

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
