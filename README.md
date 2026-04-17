# Lab 06 — Production AI Agent

Production-ready AI agent combining all Day 12 concepts in a single deployable project.

## Features

- Multi-stage Dockerfile (image < 500 MB, non-root user)
- API key authentication via `X-API-Key` header
- Sliding-window rate limiting (10 req/min per key)
- Token-based cost guard ($1/user/day, $10 global/day)
- Health (`/health`) and readiness (`/ready`) probes
- Structured JSON logging
- Graceful SIGTERM shutdown
- Stateless design — session state in Redis
- No hardcoded secrets — 12-factor config via environment variables

## Structure

```
06-lab-complete/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI application
│   ├── config.py        # 12-factor settings
│   ├── auth.py          # X-API-Key authentication
│   ├── rate_limiter.py  # Sliding-window rate limiter
│   └── cost_guard.py    # Per-user & global budget guard
├── utils/
│   ├── __init__.py
│   └── mock_llm.py      # Drop-in mock (swap for real LLM)
├── Dockerfile           # Multi-stage production build
├── docker-compose.yml   # Agent + Redis stack
├── railway.toml         # Railway deploy config
├── render.yaml          # Render deploy config
├── .env.example         # Environment variable template
├── .dockerignore
├── requirements.txt
├── DEPLOYMENT.md        # Live URL + test commands
└── README.md
```

## Quick Start (Local)

```bash
# 1. Create env file
cp .env.example .env.local
# Edit .env.local — set AGENT_API_KEY to any secret string

# 2. Start the stack
docker compose up --build

# 3. Health check
curl http://localhost:8000/health

# 4. Ask a question
curl -X POST http://localhost:8000/ask \
  -H "X-API-Key: $(grep AGENT_API_KEY .env.local | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "student", "question": "What is deployment?"}'
```

## Deploy to Railway

```bash
npm i -g @railway/cli
railway login
railway init
railway variables set ENVIRONMENT=production
railway variables set AGENT_API_KEY=<your-secret>
railway variables set OPENAI_API_KEY=<your-key>   # optional
railway up
railway domain   # → public URL
```

## Deploy to Render

1. Push repo to GitHub.
2. Render Dashboard → **New** → **Blueprint** → connect repo.
3. Render reads `render.yaml` automatically.
4. Set secrets: `AGENT_API_KEY`, `OPENAI_API_KEY`.
5. Click **Apply** → get public URL.

## Production Readiness Check

```bash
python check_production_ready.py
```
