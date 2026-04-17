"""Sliding-window rate limiter — Redis sorted-set when available, in-memory fallback."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, deque] = defaultdict(deque)

    # ── Redis path ─────────────────────────────────────────────────────────────

    def _check_redis(self, r, key: str) -> None:
        now = time.time()
        rkey = f"rl:{key}"
        cutoff = now - self.window_seconds

        pipe = r.pipeline()
        pipe.zremrangebyscore(rkey, "-inf", cutoff)
        pipe.zcard(rkey)
        _, count = pipe.execute()

        if count >= self.max_requests:
            oldest = r.zrange(rkey, 0, 0, withscores=True)
            retry_after = int(oldest[0][1] + self.window_seconds - now) + 1 if oldest else self.window_seconds
            self._raise_429(retry_after)

        # Use unique member to avoid collisions on same timestamp
        r.zadd(rkey, {f"{now}:{id(object())}": now})
        r.expire(rkey, self.window_seconds + 1)

    # ── In-memory path ─────────────────────────────────────────────────────────

    def _check_memory(self, key: str) -> None:
        now = time.time()
        window = self._windows[key]
        cutoff = now - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= self.max_requests:
            retry_after = int(window[0] + self.window_seconds - now) + 1
            self._raise_429(retry_after)

        window.append(now)

    def _raise_429(self, retry_after: int) -> None:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": self.max_requests,
                "window_seconds": self.window_seconds,
                "retry_after_seconds": retry_after,
            },
            headers={
                "X-RateLimit-Limit": str(self.max_requests),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                "Retry-After": str(retry_after),
            },
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def check(self, key: str) -> None:
        from app.redis_client import get_redis
        r = get_redis()
        if r:
            self._check_redis(r, key)
        else:
            self._check_memory(key)

    def stats(self, key: str) -> dict:
        from app.redis_client import get_redis
        r = get_redis()
        if r:
            now = time.time()
            active = r.zcount(f"rl:{key}", now - self.window_seconds, "+inf")
            return {
                "requests_in_window": int(active),
                "limit": self.max_requests,
                "remaining": max(0, self.max_requests - int(active)),
                "backend": "redis",
            }
        now = time.time()
        active = sum(1 for t in self._windows[key] if t >= now - self.window_seconds)
        return {
            "requests_in_window": active,
            "limit": self.max_requests,
            "remaining": max(0, self.max_requests - active),
            "backend": "memory",
        }


# Singleton — 10 req/min per API key
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
