"""Shared Redis client — connects once on first call, in-memory fallback if unavailable."""
from __future__ import annotations

import logging
from typing import Optional

import redis

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None
_connected: bool = False


def get_redis() -> Optional[redis.Redis]:
    global _client, _connected
    if _client is not None:
        return _client if _connected else None

    from app.config import settings

    if not settings.redis_url:
        logger.warning("REDIS_URL not set — in-memory fallback active")
        return None

    try:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        _client.ping()
        _connected = True
        logger.info("Redis connected: %s", settings.redis_url.split("@")[-1])
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — in-memory fallback active", exc)
        _connected = False

    return _client if _connected else None


def is_connected() -> bool:
    return _connected
