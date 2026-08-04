"""
Token Budget Management for LLM Gateway.
Enforces hierarchical budgets: Org -> Tenant -> User -> Pipeline.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from collections import defaultdict

from app.core.config import settings


@dataclass
class BudgetConfig:
    """Budget configuration for a scope."""
    soft_limit: int  # Warning threshold (tokens)
    hard_limit: int  # Hard limit (tokens)
    emergency_limit: int  # Emergency limit (tokens)
    reset_interval_seconds: int = 86400  # Daily reset


@dataclass
class BudgetState:
    """Current budget state."""
    used_tokens: int = 0
    limit: int = 0
    last_reset: float = field(default_factory=time.time)
    warnings_issued: int = 0


class TokenBudgetManager:
    """
    Manages token budgets across hierarchical scopes.
    
    Hierarchy: Organization -> Tenant -> User -> Pipeline
    Each level has soft/hard/emergency limits with escalating actions.
    """

    DEFAULT_CONFIGS = {
        "organization": BudgetConfig(soft_limit=8_000_000, hard_limit=10_000_000, emergency_limit=12_000_000),
        "tenant": BudgetConfig(soft_limit=1_600_000, hard_limit=2_000_000, emergency_limit=2_400_000),
        "user": BudgetConfig(soft_limit=400_000, hard_limit=500_000, emergency_limit=600_000),
        "pipeline": BudgetConfig(soft_limit=800_000, hard_limit=1_000_000, emergency_limit=1_200_000),
    }

    def __init__(self):
        self.budgets: Dict[str, BudgetState] = defaultdict(BudgetState)
        self.configs: Dict[str, BudgetConfig] = self.DEFAULT_CONFIGS.copy()
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._initialized = False

    async def initialize(self):
        """Initialize budget manager."""
        # In production, load from Redis/database
        self._initialized = True

    def _get_budget_key(self, scope: str, identifier: str) -> str:
        """Generate budget key."""
        return f"{scope}:{identifier}"

    def _check_reset(self, state: BudgetState, config: BudgetConfig):
        """Check and perform budget reset if interval elapsed."""
        if time.time() - state.last_reset >= config.reset_interval_seconds:
            state.used_tokens = 0
            state.warnings_issued = 0
            state.last_reset = time.time()

    async def check_budget(self, tenant_id: str, estimated_tokens: int) -> bool:
        """
        Check if request fits within budget.
        Returns True if allowed, False if hard limit exceeded.
        """
        # Check tenant budget
        tenant_key = self._get_budget_key("tenant", tenant_id)
        async with self._locks[tenant_key]:
            state = self.budgets[tenant_key]
            config = self.configs["tenant"]
            self._check_reset(state, config)

            if state.used_tokens + estimated_tokens > config.hard_limit:
                return False

        return True

    async def record_usage(self, tenant_id: str, tokens: int):
        """Record token usage for tenant."""
        tenant_key = self._get_budget_key("tenant", tenant_id)
        async with self._locks[tenant_key]:
            state = self.budgets[tenant_key]
            config = self.configs["tenant"]
            self._check_reset(state, config)

            state.used_tokens += tokens
            state.limit = config.hard_limit

            # Check warning thresholds
            usage_pct = state.used_tokens / config.hard_limit
            if usage_pct >= 0.8 and state.warnings_issued < 1:
                state.warnings_issued = 1
                # Emit warning event
                print(f"WARNING: Tenant {tenant_id} at 80% token budget")
            elif usage_pct >= 1.0 and state.warnings_issued < 2:
                state.warnings_issued = 2
                print(f"ALERT: Tenant {tenant_id} exceeded token budget")

    async def get_budget_status(self, tenant_id: str) -> Dict[str, Any]:
        """Get current budget status for tenant."""
        tenant_key = self._get_budget_key("tenant", tenant_id)
        state = self.budgets[tenant_key]
        config = self.configs["tenant"]
        self._check_reset(state, config)

        return {
            "used_tokens": state.used_tokens,
            "limit": config.hard_limit,
            "remaining": max(0, config.hard_limit - state.used_tokens),
            "usage_percent": round(state.used_tokens / config.hard_limit * 100, 1),
            "status": self._get_status(state, config),
        }

    def _get_status(self, state: BudgetState, config: BudgetConfig) -> str:
        """Determine budget status."""
        pct = state.used_tokens / config.hard_limit
        if pct >= 1.0:
            return "exceeded"
        elif pct >= 0.8:
            return "warning"
        elif pct >= 1.2:
            return "emergency"
        return "healthy"

    def set_config(self, scope: str, config: BudgetConfig):
        """Update budget configuration for a scope."""
        self.configs[scope] = config