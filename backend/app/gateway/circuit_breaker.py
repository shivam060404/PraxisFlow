"""
Circuit Breaker for LLM Gateway.
Implements circuit breaker pattern for provider resilience.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: int = 60
    half_open_max_calls: int = 3


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    state: CircuitState = CircuitState.CLOSED


class CircuitBreaker:
    """
    Circuit breaker for LLM provider resilience.
    Monitors provider health and prevents cascade failures.
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.circuits: Dict[str, CircuitStats] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._initialized = False

    async def initialize(self):
        """Initialize circuit breaker."""
        self._initialized = True

    def _get_lock(self, model: str) -> asyncio.Lock:
        """Get or create lock for model."""
        if model not in self._locks:
            self._locks[model] = asyncio.Lock()
        return self._locks[model]

    def _get_circuit(self, model: str) -> CircuitStats:
        """Get or create circuit for model."""
        if model not in self.circuits:
            self.circuits[model] = CircuitStats()
        return self.circuits[model]

    async def is_open(self, model: str) -> bool:
        """Check if circuit is open for model."""
        circuit = self._get_circuit(model)

        if circuit.state == CircuitState.OPEN:
            # Check if timeout expired
            if time.time() - circuit.last_failure_time >= self.config.timeout_seconds:
                circuit.state = CircuitState.HALF_OPEN
                circuit.consecutive_successes = 0
                logger.info(f"Circuit for {model} transitioned to HALF_OPEN")
                return False
            return True

        return False

    async def record_success(self, model: str):
        """Record successful call."""
        circuit = self._get_circuit(model)
        async with self._get_lock(model):
            circuit.total_calls += 1
            circuit.successful_calls += 1
            circuit.consecutive_successes += 1
            circuit.consecutive_failures = 0
            circuit.last_success_time = time.time()

            if circuit.state == CircuitState.HALF_OPEN:
                if circuit.consecutive_successes >= self.config.success_threshold:
                    circuit.state = CircuitState.CLOSED
                    circuit.consecutive_failures = 0
                    logger.info(f"Circuit for {model} CLOSED after recovery")

    async def record_failure(self, model: str):
        """Record failed call."""
        circuit = self._get_circuit(model)
        async with self._get_lock(model):
            circuit.total_calls += 1
            circuit.failed_calls += 1
            circuit.consecutive_failures += 1
            circuit.consecutive_successes = 0
            circuit.last_failure_time = time.time()

            if circuit.state == CircuitState.CLOSED:
                if circuit.consecutive_failures >= self.config.failure_threshold:
                    circuit.state = CircuitState.OPEN
                    logger.warning(f"Circuit for {model} OPENED after {circuit.consecutive_failures} failures")

            elif circuit.state == CircuitState.HALF_OPEN:
                circuit.state = CircuitState.OPEN
                logger.warning(f"Circuit for {model} re-OPENED after failure in HALF_OPEN")

    async def get_status(self, model: str) -> Dict[str, Any]:
        """Get circuit breaker status for model."""
        circuit = self._get_circuit(model)
        return {
            "model": model,
            "state": circuit.state.value,
            "total_calls": circuit.total_calls,
            "successful_calls": circuit.successful_calls,
            "failed_calls": circuit.failed_calls,
            "consecutive_failures": circuit.consecutive_failures,
            "consecutive_successes": circuit.consecutive_successes,
            "last_failure": circuit.last_failure_time,
            "last_success": circuit.last_success_time,
        }

    async def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status for all circuits."""
        return {model: await self.get_status(model) for model in self.circuits}

    async def reset(self, model: str):
        """Manually reset circuit for model."""
        circuit = self._get_circuit(model)
        async with self._get_lock(model):
            circuit.state = CircuitState.CLOSED
            circuit.consecutive_failures = 0
            circuit.consecutive_successes = 0
            logger.info(f"Circuit for {model} manually reset")

    async def force_open(self, model: str):
        """Force circuit open for model."""
        circuit = self._get_circuit(model)
        async with self._get_lock(model):
            circuit.state = CircuitState.OPEN
            circuit.last_failure_time = time.time()
            logger.warning(f"Circuit for {model} force OPENED")

    def get_health_score(self, model: str) -> float:
        """Calculate health score (0.0 - 1.0)."""
        circuit = self._get_circuit(model)
        if circuit.total_calls == 0:
            return 1.0
        return circuit.successful_calls / circuit.total_calls