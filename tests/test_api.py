"""
Integration tests for the AI Agent API.

Each test is independent — shared state (rate limiter, cost guard) lives in
module-level singletons, so tests that exercise limits use unique keys.
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY

# ── Public endpoints ──────────────────────────────────────────────────────────

def test_root_returns_app_info(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "app" in data
    assert "endpoints" in data


def test_health_returns_ok(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert "version" in data


def test_ready_returns_true_after_startup(client: TestClient):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["ready"] is True


# ── Authentication ─────────────────────────────────────────────────────────────

def test_ask_rejects_missing_key(client: TestClient):
    r = client.post("/ask", json={"question": "hello"})
    assert r.status_code == 401


def test_ask_rejects_wrong_key(client: TestClient):
    r = client.post("/ask", json={"question": "hello"}, headers={"X-API-Key": "not-valid"})
    assert r.status_code == 401


def test_metrics_rejects_missing_key(client: TestClient):
    r = client.get("/metrics")
    assert r.status_code == 401


# ── /ask happy path ───────────────────────────────────────────────────────────

def test_ask_returns_answer(client: TestClient):
    r = client.post(
        "/ask",
        json={"user_id": "test-user", "question": "What is Docker?"},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["question"] == "What is Docker?"
    assert isinstance(data["answer"], str) and len(data["answer"]) > 0
    assert "timestamp" in data
    assert "model" in data


def test_ask_default_user_id(client: TestClient):
    r = client.post(
        "/ask",
        json={"question": "hello"},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert r.status_code == 200
    assert r.json()["user_id"] == "anonymous"


# ── Input validation ──────────────────────────────────────────────────────────

def test_ask_rejects_empty_question(client: TestClient):
    r = client.post(
        "/ask",
        json={"question": ""},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert r.status_code == 422


def test_ask_rejects_question_too_long(client: TestClient):
    r = client.post(
        "/ask",
        json={"question": "x" * 2001},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert r.status_code == 422


def test_ask_rejects_missing_question_field(client: TestClient):
    r = client.post(
        "/ask",
        json={"user_id": "test"},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert r.status_code == 422


# ── Metrics ───────────────────────────────────────────────────────────────────

def test_metrics_returns_stats(client: TestClient):
    r = client.get("/metrics", headers={"X-API-Key": TEST_API_KEY})
    assert r.status_code == 200
    data = r.json()
    assert "uptime_seconds" in data
    assert "total_requests" in data


# ── Security headers ──────────────────────────────────────────────────────────

def test_security_headers_present(client: TestClient):
    r = client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


# ── Rate limiter (unit test — avoids shared HTTP state) ───────────────────────

def test_rate_limiter_blocks_after_limit():
    from fastapi import HTTPException

    from app.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.check("unit-test-user")

    with pytest.raises(HTTPException) as exc:
        limiter.check("unit-test-user")

    assert exc.value.status_code == 429


def test_rate_limiter_independent_keys():
    from app.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.check("user-a")
    limiter.check("user-a")
    # user-b has a clean window
    limiter.check("user-b")
    limiter.check("user-b")


# ── Cost guard (unit test) ────────────────────────────────────────────────────

def test_cost_guard_records_usage():
    from app.cost_guard import CostGuard

    guard = CostGuard(per_user_budget_usd=1.0, global_budget_usd=10.0)
    guard.check("cost-user")
    guard.record("cost-user", input_tokens=100, output_tokens=50)
    usage = guard.usage("cost-user")

    assert usage["requests"] == 1
    assert usage["cost_usd"] > 0
    assert usage["remaining_usd"] < 1.0


def test_cost_guard_blocks_over_budget():
    from fastapi import HTTPException

    from app.cost_guard import CostGuard

    guard = CostGuard(per_user_budget_usd=0.000001, global_budget_usd=10.0)
    guard.record("broke-user", input_tokens=10000, output_tokens=10000)

    with pytest.raises(HTTPException) as exc:
        guard.check("broke-user")

    assert exc.value.status_code == 402
