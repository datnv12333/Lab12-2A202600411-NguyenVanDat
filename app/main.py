"""Production AI Agent entry point.

Wires together all production concerns:
  - 12-factor config (app/config.py)
  - API key authentication (app/auth.py)
  - Rate limiting — 10 req/min (app/rate_limiter.py)
  - Cost guard — $10/day global (app/cost_guard.py)
  - Conversation history — Redis-backed, in-memory fallback
  - Structured JSON logging
  - Health + readiness probes
  - Graceful shutdown via SIGTERM
  - Security headers, CORS
"""
import json
import logging
import signal
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import cost_guard
from app.rate_limiter import rate_limiter
from utils.mock_llm import ask as llm_ask

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":%(message)s}',
)
logger = logging.getLogger(__name__)

# ── App state ─────────────────────────────────────────────────────────────────
_start_time = time.time()
_is_ready = False
_request_count = 0
_error_count = 0

# ── Conversation history ──────────────────────────────────────────────────────
_CONV_MAX_MESSAGES = 20
_CONV_TTL = 3600  # seconds
_mem_history: dict[str, list] = defaultdict(list)  # in-memory fallback


def _history_key(user_id: str) -> str:
    return f"conv:{user_id}"


def _load_history(user_id: str) -> list[dict]:
    from app.redis_client import get_redis
    r = get_redis()
    if r:
        raw = r.lrange(_history_key(user_id), 0, -1)
        return [json.loads(m) for m in raw]
    return list(_mem_history[user_id])


def _append_message(user_id: str, role: str, content: str) -> None:
    from app.redis_client import get_redis
    msg = json.dumps({"role": role, "content": content})
    r = get_redis()
    if r:
        rkey = _history_key(user_id)
        r.rpush(rkey, msg)
        r.ltrim(rkey, -_CONV_MAX_MESSAGES, -1)
        r.expire(rkey, _CONV_TTL)
    else:
        _mem_history[user_id].append(json.loads(msg))
        if len(_mem_history[user_id]) > _CONV_MAX_MESSAGES:
            _mem_history[user_id] = _mem_history[user_id][-_CONV_MAX_MESSAGES:]


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    # Eagerly try Redis on startup so the first request doesn't pay the connect cost
    from app.redis_client import get_redis
    get_redis()

    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }))
    time.sleep(0.1)  # warm-up
    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def _observability(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.time() - start) * 1000, 1),
        }))
        return response
    except Exception:
        _error_count += 1
        raise


# ── Schemas ───────────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    user_id: str = Field(default="anonymous", max_length=64)
    question: str = Field(..., min_length=1, max_length=2000)


class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    model: str
    history_length: int
    timestamp: str


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask": "POST /ask  (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "metrics": "GET /metrics  (requires X-API-Key)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    api_key: str = Depends(verify_api_key),
):
    """Send a question to the AI agent. Maintains conversation history per user_id.

    **Auth:** `X-API-Key: <key>`
    """
    rate_limiter.check(api_key[:16])
    cost_guard.check(body.user_id)

    # Load conversation history before calling LLM
    history = _load_history(body.user_id)
    _append_message(body.user_id, "user", body.question)

    logger.info(json.dumps({
        "event": "agent_call",
        "user_id": body.user_id,
        "q_len": len(body.question),
        "history_len": len(history),
    }))

    answer = llm_ask(body.question)

    _append_message(body.user_id, "assistant", answer)

    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    cost_guard.record(body.user_id, input_tokens, output_tokens)

    return AskResponse(
        user_id=body.user_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        history_length=len(history) + 2,  # prior messages + this exchange
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe — platform restarts container if this fails."""
    from app.redis_client import is_connected
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "llm": "mock" if not settings.openai_api_key else "openai",
        "redis_connected": is_connected(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe — load balancer stops routing here when not ready."""
    if not _is_ready:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Not ready")
    return {"ready": True}


@app.get("/metrics", tags=["Operations"])
def metrics(api_key: str = Depends(verify_api_key)):
    """Operational metrics (protected)."""
    from app.redis_client import is_connected
    rl = rate_limiter.stats(api_key[:16])
    usage = cost_guard.usage("__system__")
    return {
        "uptime_seconds": round(time.time() - _start_time, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "rate_limit": rl,
        "daily_spend_usd": usage["cost_usd"],
        "daily_budget_usd": cost_guard.global_budget_usd,
        "redis_connected": is_connected(),
        "environment": settings.environment,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# ── Graceful shutdown ─────────────────────────────────────────────────────────
def _on_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal_received", "signum": signum}))

signal.signal(signal.SIGTERM, _on_signal)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
