"""Token-based cost guard — Redis-backed when available, in-memory fallback."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings as _settings

logger = logging.getLogger(__name__)

_INPUT_PRICE_PER_1K = 0.00015   # GPT-4o-mini: $0.15 / 1M input tokens
_OUTPUT_PRICE_PER_1K = 0.0006   # GPT-4o-mini: $0.60 / 1M output tokens
_TTL = 172800                   # 48h — keys auto-expire after day rolls over


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class _DailyUsage:
    user_id: str
    day: str = field(default_factory=_today)
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0

    @property
    def cost_usd(self) -> float:
        return round(
            self.input_tokens / 1000 * _INPUT_PRICE_PER_1K
            + self.output_tokens / 1000 * _OUTPUT_PRICE_PER_1K,
            6,
        )


class CostGuard:
    def __init__(
        self,
        per_user_budget_usd: float = 1.0,
        global_budget_usd: float = 10.0,
        warn_threshold: float = 0.8,
    ):
        self.per_user_budget_usd = per_user_budget_usd
        self.global_budget_usd = global_budget_usd
        self.warn_threshold = warn_threshold
        # In-memory fallback state
        self._records: dict[str, _DailyUsage] = {}
        self._global_day = _today()
        self._global_cost = 0.0

    # ── Redis helpers ──────────────────────────────────────────────────────────

    def _redis_user_key(self, user_id: str) -> str:
        return f"cost:{_today()}:{user_id}"

    def _redis_global_key(self) -> str:
        return f"cost:{_today()}:__global__"

    def _redis_get_user(self, r, user_id: str) -> _DailyUsage:
        raw = r.hgetall(self._redis_user_key(user_id))
        return _DailyUsage(
            user_id=user_id,
            day=_today(),
            input_tokens=int(raw.get("input_tokens", 0)),
            output_tokens=int(raw.get("output_tokens", 0)),
            request_count=int(raw.get("request_count", 0)),
        )

    def _redis_get_global_cost(self, r) -> float:
        val = r.get(self._redis_global_key())
        return float(val) if val else 0.0

    def _redis_record(self, r, user_id: str, input_tokens: int, output_tokens: int) -> _DailyUsage:
        ukey = self._redis_user_key(user_id)
        pipe = r.pipeline()
        pipe.hincrby(ukey, "input_tokens", input_tokens)
        pipe.hincrby(ukey, "output_tokens", output_tokens)
        pipe.hincrby(ukey, "request_count", 1)
        pipe.expire(ukey, _TTL)
        pipe.execute()

        call_cost = (
            input_tokens / 1000 * _INPUT_PRICE_PER_1K
            + output_tokens / 1000 * _OUTPUT_PRICE_PER_1K
        )
        gkey = self._redis_global_key()
        r.incrbyfloat(gkey, call_cost)
        r.expire(gkey, _TTL)

        return self._redis_get_user(r, user_id)

    # ── In-memory helpers ──────────────────────────────────────────────────────

    def _mem_get(self, user_id: str) -> _DailyUsage:
        today = _today()
        rec = self._records.get(user_id)
        if not rec or rec.day != today:
            self._records[user_id] = _DailyUsage(user_id=user_id, day=today)
        return self._records[user_id]

    def _mem_reset_global(self) -> None:
        today = _today()
        if today != self._global_day:
            self._global_cost = 0.0
            self._global_day = today

    # ── Public API ─────────────────────────────────────────────────────────────

    def check(self, user_id: str) -> None:
        """Call before LLM request. Raises 503 (global) or 402 (per-user) if over budget."""
        from app.redis_client import get_redis
        r = get_redis()

        if r:
            global_cost = self._redis_get_global_cost(r)
            rec = self._redis_get_user(r, user_id)
        else:
            self._mem_reset_global()
            global_cost = self._global_cost
            rec = self._mem_get(user_id)

        if global_cost >= self.global_budget_usd:
            logger.critical("Global daily budget exceeded: $%.4f", global_cost)
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable due to budget limits. Try again tomorrow.",
            )

        if rec.cost_usd >= self.per_user_budget_usd:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Daily user budget exceeded",
                    "used_usd": rec.cost_usd,
                    "budget_usd": self.per_user_budget_usd,
                    "resets_at": "midnight UTC",
                },
            )

        pct = rec.cost_usd / self.per_user_budget_usd
        if pct >= self.warn_threshold:
            logger.warning("User %s at %.0f%% of daily budget", user_id, pct * 100)

    def record(self, user_id: str, input_tokens: int, output_tokens: int) -> _DailyUsage:
        """Call after LLM response is received."""
        from app.redis_client import get_redis
        r = get_redis()

        if r:
            rec = self._redis_record(r, user_id, input_tokens, output_tokens)
        else:
            rec = self._mem_get(user_id)
            rec.input_tokens += input_tokens
            rec.output_tokens += output_tokens
            rec.request_count += 1
            call_cost = (
                input_tokens / 1000 * _INPUT_PRICE_PER_1K
                + output_tokens / 1000 * _OUTPUT_PRICE_PER_1K
            )
            self._global_cost += call_cost

        logger.info(
            "cost_record user=%s requests=%d cost=$%.6f budget=$%.2f",
            user_id, rec.request_count, rec.cost_usd, self.per_user_budget_usd,
        )
        return rec

    def usage(self, user_id: str) -> dict:
        from app.redis_client import get_redis
        r = get_redis()
        rec = self._redis_get_user(r, user_id) if r else self._mem_get(user_id)
        return {
            "user_id": user_id,
            "date": rec.day,
            "requests": rec.request_count,
            "input_tokens": rec.input_tokens,
            "output_tokens": rec.output_tokens,
            "cost_usd": rec.cost_usd,
            "budget_usd": self.per_user_budget_usd,
            "remaining_usd": max(0.0, round(self.per_user_budget_usd - rec.cost_usd, 6)),
            "budget_used_pct": round(rec.cost_usd / self.per_user_budget_usd * 100, 1),
        }


# Singleton — reads budget from env via settings
cost_guard = CostGuard(
    per_user_budget_usd=_settings.daily_budget_usd,
    global_budget_usd=_settings.daily_budget_usd * 10,
)
