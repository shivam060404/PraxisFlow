"""
Token Budget Management for LLM Gateway.
Enforces hierarchical budgets: Org -> Tenant -> User -> Pipeline.

Counters are stored in Redis (INCRBY with a daily key), so budgets hold
across API workers and Celery processes. Falls back to per-process memory
when Redis is unreachable.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from collections import defaultdict

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BudgetConfig:
    """Budget configuration for a scope."""
    soft_limit: int   # Warning threshold (tokens)
    hard_limit: int   # Hard limit (tokens)
    emergency_limit: int  # Emergency limit (tokens)
    reset_interval_seconds: int = 86400  # Daily reset


@dataclass
class BudgetState:
    """In-memory fallback budget state."""

    used_tokens: int = 0
    limit: int = 0
    last_reset: float = field(default_factory=time.time)


class TokenBudgetManager:
    """
    Redis-backed hierarchical token budgets.

    Keys are day-scoped (`budget:{scope}:{id}:YYYYMMDD`), which makes the
    daily reset implicit and atomic. When Redis cannot be reached the
    manager degrades to in-memory counters and says so in the logs.
    """

    DEFAULT_CONFIGS = {
        "organization": BudgetConfig(soft_limit=8_000_000, hard_limit=10_000_000, emergency_limit=12_000_000),
        "tenant": BudgetConfig(soft_limit=1_600_000, hard_limit=2_000_000, emergency_limit=2_400_000),
        "user": BudgetConfig(soft_limit=400_000, hard_limit=500_000, emergency_limit=600_000),
        "pipeline": BudgetConfig(soft_limit=800_000, hard_limit=1_000_000, emergency_limit=1_200_000),
    }

    def __init__(self):
        self.budgets: Dict[str, BudgetState] = defaultdict(BudgetState)
        self.configs: Dict[str, BudgetConfig] = dict(self.DEFAULT_CONFIGS)
        self._redis = None
        self._redis_loop = None
        self._redis_available = False
        self._initialized = False

    async def initialize(self):
        """Connect to Redis if configured; degrade gracefully otherwise."""
        try:
            import redis.asyncio as redis_lib

            self._redis = redis_lib.from_url(settings.REDIS_URL)
            await self._redis.ping()
            self._redis_available = True
            logger.info("Budget manager: Redis backend")
        except Exception as e:
            logger.warning(f"Budget manager: Redis unavailable ({e}); using in-process counters")
            self._redis = None
            self._redis_available = False
        self._initialized = True

    async def close(self):
        """Release the Redis connection inside its owning loop."""
        if self._redis is not None and self._redis_loop is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
            self._redis_available = False

    async def _get_redis(self):
        """Return a Redis client bound to the *current* running loop."""
        import asyncio
        import redis.asyncio as redis_lib

        current_loop = asyncio.get_running_loop()
        if self._redis is None or self._redis_loop is not current_loop:
            self._redis = redis_lib.from_url(settings.REDIS_URL)
            self._redis_loop = current_loop
        return self._redis

    @staticmethod
    def _day_key(scope: str, identifier: str) -> str:
        day = time.strftime("%Y%m%d", time.gmtime())
        return f"budget:{scope}:{identifier}:{day}"

    @staticmethod
    def _check_reset(state: BudgetState, config: BudgetConfig) -> None:
        if time.time() - state.last_reset >= config.reset_interval_seconds:
            state.used_tokens = 0
            state.last_reset = time.time()

    async def _get_used(self, scope: str, identifier: str) -> int:
        config = self.configs[scope]
        if self._redis_available:
            try:
                client = await self._get_redis()
                value = await client.get(self._day_key(scope, identifier))
                return int(value or 0)
            except Exception as e:
                logger.warning(f"Budget read failed ({e}); using local counter")
                self._redis_available = False

        state = self.budgets[f"{scope}:{identifier}"]
        self._check_reset(state, config)
        return state.used_tokens

    async def check_budget(self, tenant_id: str, estimated_tokens: int) -> bool:
        """Return True if the request fits within the tenant's hard limit."""
        used = await self._get_used("tenant", tenant_id)
        return used + estimated_tokens <= self.configs["tenant"].hard_limit

    async def record_usage(self, scope: str, identifier: str, tokens: int):
        """
        Record token usage for a scope.

        Accepts either (tenant_id, tokens) legacy positional form or the full
        (scope, identifier, tokens) form.
        """
        # Legacy call shape: record_usage(tenant_id, tokens)
        if isinstance(identifier, int) and tokens is None:
            scope, identifier, tokens = "tenant", scope, identifier

        config = self.configs[scope]
        key = f"{scope}:{identifier}"

        if self._redis_available:
            try:
                r = await self._get_redis()
                day_key = self._day_key(scope, identifier)
                new_total = await r.incrby(day_key, tokens)
                if new_total == tokens:
                    await r.expire(day_key, config.reset_interval_seconds * 2)
                used = new_total
            except Exception as e:
                logger.warning(f"Budget write failed ({e}); using local counter")
                self._redis_available = False
                used = None
        else:
            used = None

        if used is None:
            state = self.budgets[key]
            self._check_reset(state, config)
            state.used_tokens += tokens
            state.limit = config.hard_limit
            used = state.used_tokens

        usage_pct = used / config.hard_limit if config.hard_limit else 0
        if usage_pct >= 1.0:
            logger.error(f"ALERT: {scope} {identifier} exceeded token budget ({used}/{config.hard_limit})")
        elif usage_pct >= 0.8:
            logger.warning(f"WARNING: {scope} {identifier} at 80%%+ of token budget ({used}/{config.hard_limit})")

    async def get_budget_status(self, tenant_id: str) -> Dict[str, Any]:
        """Current tenant budget status."""
        config = self.configs["tenant"]
        used = await self._get_used("tenant", tenant_id)

        return {
            "used_tokens": used,
            "limit": config.hard_limit,
            "remaining": max(0, config.hard_limit - used),
            "usage_percent": round(used / config.hard_limit * 100, 1) if config.hard_limit else 0,
            "status": self._get_status(used, config),
        }

    def _get_status(self, used: int, config: BudgetConfig) -> str:
        pct = used / config.hard_limit if config.hard_limit else 0
        if pct >= 1.2:
            return "emergency"
        elif pct >= 1.0:
            return "exceeded"
        elif pct >= 0.8:
            return "warning"
        return "healthy"

    def set_config(self, scope: str, config: BudgetConfig):
        """Update budget configuration for a scope."""
        self.configs[scope] = config
