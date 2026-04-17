"""
Pytest configuration.

os.environ must be set BEFORE app modules are imported,
because app/config.py reads env vars at module level.
"""
import os

os.environ.setdefault("AGENT_API_KEY", "ci-test-key-do-not-use-in-prod")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET", "ci-jwt-secret")

import pytest
from fastapi.testclient import TestClient

from app.main import app

TEST_API_KEY = os.environ["AGENT_API_KEY"]


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Session-scoped TestClient — triggers lifespan startup/shutdown once."""
    with TestClient(app) as c:
        yield c
