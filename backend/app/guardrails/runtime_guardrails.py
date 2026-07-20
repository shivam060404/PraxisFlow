"""
Runtime Guardrails - NeMo Integration and Token/Temperature/Circuit Breaker controls
These run DURING the LLM call via NeMo Guardrails or as pre-call checks.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from app.guardrails.base import BaseGuardrail, GuardrailAction, GuardrailLayer, GuardrailSeverity, GuardrailResult, GuardrailContext
from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── NeMo Guardrails Runtime ───

class NeMoGuardrailsRuntime(BaseGuardrail):
    """
    Integration with NVIDIA NeMo Guardrails for runtime enforcement.
    Uses Colang policies to control LLM behavior during generation.
    """

    def __init__(
        self,
        enabled: bool = True,
        colang_config_path: str = "guardrails/colang/extraction_policies.co",
        rails_config: Dict = None,
    ):
        super().__init__("nemo_guardrails", GuardrailLayer.RUNTIME, enabled)
        self.colang_config_path = colang_config_path
        self.rails_config = rails_config or {}
        self._rails = None
        self._initialized = False

    async def initialize(self):
        """Initialize NeMo Guardrails runtime."""
        if not self.enabled:
            return

        try:
            from nemoguardrails import RailsConfig
            from nemoguardrails import LLMRails

            # Load Colang config
            config = RailsConfig.from_path(self.colang_config_path)

            # Apply runtime config overrides
            if self.rails_config:
                config.rails = self.rails_config

            self._rails = LLMRails(config)
            self._initialized = True
            logger.info("NeMo Guardrails runtime initialized")

        except ImportError:
            logger.warning("NeMo Guardrails not installed. Runtime guardrails disabled.")
            self.enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize NeMo Guardrails: {e}")
            self.enabled = False

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        """
        Check content through NeMo Guardrails.
        Note: In practice, NeMo wraps the LLM call, so this is more of a
        pre-flight check. The actual enforcement happens during generation.
        """
        if not self.enabled or not self._initialized:
            return self._create_result(
                GuardrailAction.ALLOW,
                GuardrailSeverity.INFO,
                "NeMo Guardrails not available",
            )

        try:
            # NeMo Guardrails works by wrapping the LLM call
            # This check validates the prompt against input rails
            result = await self._rails.generate_async(
                prompt=content,
                context={
                    "tenant_id": context.tenant_id,
                    "meeting_id": context.meeting_id,
                    "pipeline_node": context.pipeline_node,
                    "transcript_context": context.transcript_context,
                    "model_config": context.model_config,
                }
            )

            # Check if any rails blocked
            if result.get("blocked", False):
                return self._create_result(
                    GuardrailAction.BLOCK,
                    GuardrailSeverity.WARNING,
                    "NeMo Guardrails blocked generation",
                    metadata={"nemo_result": result},
                )

            # Check if output was modified (e.g., format correction)
            if result.get("content") != content:
                return self._create_result(
                    GuardrailAction.RETRY,  # Signal to retry with corrected format
                    GuardrailSeverity.INFO,
                    "NeMo Guardrails modified output",
                    modified_content=result.get("content"),
                    metadata={"nemo_result": result},
                )

            return self._create_result(
                GuardrailAction.ALLOW,
                GuardrailSeverity.INFO,
                "NeMo Guardrails passed",
                metadata={"nemo_result": result},
            )

        except Exception as e:
            logger.error(f"NeMo Guardrails error: {e}")
            # Fail open for availability
            return self._create_result(
                GuardrailAction.ALLOW,
                GuardrailSeverity.WARNING,
                f"NeMo error (fail open): {str(e)}",
                confidence=0.0,
            )


# ─── Token Limit Guard ───

class TokenLimitGuard(BaseGuardrail):
    """Enforces per-request token limits based on pipeline node."""

    NODE_LIMITS = {
        "extraction": {"max_tokens": 4096, "max_input_tokens": 8000},
        "verification": {"max_tokens": 2048, "max_input_tokens": 6000},
        "entity_resolution": {"max_tokens": 1024, "max_input_tokens": 4000},
        "deduplication": {"max_tokens": 4096, "max_input_tokens": 8000},
        "conflict_resolution": {"max_tokens": 2048, "max_input_tokens": 6000},
        "summarization": {"max_tokens": 2048, "max_input_tokens": 6000},
        "default": {"max_tokens": 2048, "max_input_tokens": 4000},
    }

    def __init__(self, enabled: bool = True):
        super().__init__("token_limit", GuardrailLayer.RUNTIME, enabled)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        node = context.pipeline_node or "default"
        limits = self.NODE_LIMITS.get(node, self.NODE_LIMITS["default"])

        # Estimate tokens (rough: 4 chars per token)
        estimated_input_tokens = len(content) / 4
        max_output_tokens = context.model_config.get("max_tokens", limits["max_tokens"])

        # Check input tokens
        if estimated_input_tokens > limits["max_input_tokens"]:
            return self._create_result(
                GuardrailAction.BLOCK,
                GuardrailSeverity.WARNING,
                f"Input exceeds token limit for {node}",
                metadata={
                    "estimated_input_tokens": estimated_input_tokens,
                    "max_input_tokens": limits["max_input_tokens"],
                    "node": node,
                },
            )

        # Check requested output tokens
        if max_output_tokens > limits["max_tokens"]:
            return self._create_result(
                GuardrailAction.BLOCK,
                GuardrailSeverity.WARNING,
                f"Requested output tokens exceed limit for {node}",
                metadata={
                    "requested_output_tokens": max_output_tokens,
                    "max_output_tokens": limits["max_tokens"],
                    "node": node,
                },
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Token limits OK",
            metadata={
                "estimated_input_tokens": estimated_input_tokens,
                "max_output_tokens": max_output_tokens,
                "node": node,
            },
        )


# ─── Temperature Lock Guard ───

class TemperatureLockGuard(BaseGuardrail):
    """Locks temperature per pipeline node to prevent creative drift."""

    NODE_TEMPERATURES = {
        "extraction": 0.1,
        "verification": 0.0,
        "entity_resolution": 0.0,
        "deduplication": 0.0,
        "conflict_resolution": 0.0,
        "summarization": 0.3,
        "default": 0.1,
    }

    def __init__(self, enabled: bool = True, tolerance: float = 0.05):
        super().__init__("temperature_lock", GuardrailLayer.RUNTIME, enabled)
        self.tolerance = tolerance

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        node = context.pipeline_node or "default"
        expected_temp = self.NODE_TEMPERATURES.get(node, self.NODE_TEMPERATURES["default"])
        actual_temp = context.model_config.get("temperature", expected_temp)

        if abs(actual_temp - expected_temp) > self.tolerance:
            logger.warning(
                f"Temperature deviation for {node}: expected {expected_temp}, got {actual_temp}"
            )
            return self._create_result(
                GuardrailAction.FLAG,
                GuardrailSeverity.WARNING,
                f"Temperature deviation for {node}",
                metadata={
                    "node": node,
                    "expected_temperature": expected_temp,
                    "actual_temperature": actual_temp,
                    "deviation": abs(actual_temp - expected_temp),
                },
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Temperature locked",
            metadata={"temperature": expected_temp, "node": node},
        )


# ─── Circuit Breaker Guard ───

@dataclass
class CircuitState:
    """State of a circuit breaker for a model provider."""
    model: str
    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    is_open: bool = False
    half_open: bool = False


class CircuitBreakerGuard(BaseGuardrail):
    """Monitors provider health and triggers fallbacks via circuit breaker pattern."""

    def __init__(
        self,
        enabled: bool = True,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ):
        super().__init__("circuit_breaker", GuardrailLayer.RUNTIME, enabled)
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        self._circuits: Dict[str, CircuitState] = {}
        import time
        self._time = time

    def _get_circuit(self, model: str) -> CircuitState:
        if model not in self._circuits:
            self._circuits[model] = CircuitState(model=model)
        return self._circuits[model]

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        model = context.model_config.get("model", "unknown")
        circuit = self._get_circuit(model)

        # Check circuit state
        if circuit.is_open:
            # Check if timeout expired (transition to half-open)
            if self._time.time() - circuit.last_failure_time > self.timeout_seconds:
                circuit.is_open = False
                circuit.half_open = True
                logger.info(f"Circuit for {model} transitioning to half-open")
            else:
                return self._create_result(
                    GuardrailAction.FALLBACK,
                    GuardrailSeverity.WARNING,
                    f"Circuit open for {model}, triggering fallback",
                    metadata={
                        "model": model,
                        "state": "open",
                        "failures": circuit.failures,
                        "timeout_remaining": self.timeout_seconds - (self._time.time() - circuit.last_failure_time),
                    },
                )

        if circuit.half_open:
            # In half-open, allow limited calls
            if circuit.successes >= self.half_open_max_calls:
                # Enough successes, close circuit
                circuit.is_open = False
                circuit.half_open = False
                circuit.failures = 0
                circuit.successes = 0
                logger.info(f"Circuit for {model} closed after recovery")
            else:
                # Allow this call but track
                return self._create_result(
                    GuardrailAction.ALLOW,
                    GuardrailSeverity.INFO,
                    f"Circuit half-open for {model}, allowing test call",
                    metadata={"model": model, "state": "half-open", "test_calls": circuit.successes},
                )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Circuit closed",
            metadata={"model": model, "state": "closed"},
        )

    def record_failure(self, model: str):
        """Record a failure for the model."""
        circuit = self._get_circuit(model)
        circuit.failures += 1
        circuit.last_failure_time = self._time.time()

        if circuit.failures >= self.failure_threshold and not circuit.is_open:
            circuit.is_open = True
            circuit.half_open = False
            logger.warning(f"Circuit OPENED for {model} after {circuit.failures} failures")

    def record_success(self, model: str):
        """Record a success for the model."""
        circuit = self._get_circuit(model)
        circuit.successes += 1
        circuit.last_success_time = self._time.time()

        if circuit.is_open:
            # In half-open, count successes toward recovery
            pass
        elif circuit.failures > 0:
            # Gradual recovery
            circuit.failures = max(0, circuit.failures - 1)

    def get_circuit_status(self, model: str) -> Dict[str, Any]:
        """Get current circuit status."""
        circuit = self._get_circuit(model)
        return {
            "model": model,
            "state": "open" if circuit.is_open else ("half-open" if circuit.half_open else "closed"),
            "failures": circuit.failures,
            "successes": circuit.successes,
            "last_failure": circuit.last_failure_time,
            "last_success": circuit.last_success_time,
        }


# ─── Latency Budget Guard ───

class LatencyBudgetGuard(BaseGuardrail):
    """Enforces latency budgets per pipeline node."""

    NODE_BUDGETS_MS = {
        "extraction": 30000,
        "verification": 20000,
        "entity_resolution": 15000,
        "deduplication": 20000,
        "conflict_resolution": 20000,
        "summarization": 20000,
        "default": 20000,
    }

    def __init__(self, enabled: bool = True):
        super().__init__("latency_budget", GuardrailLayer.RUNTIME, enabled)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        node = context.pipeline_node or "default"
        budget_ms = self.NODE_BUDGETS_MS.get(node, self.NODE_BUDGETS_MS["default"])
        timeout_ms = context.model_config.get("timeout_ms", budget_ms)

        if timeout_ms > budget_ms:
            return self._create_result(
                GuardrailAction.FLAG,
                GuardrailSeverity.WARNING,
                f"Timeout exceeds budget for {node}",
                metadata={
                    "node": node,
                    "budget_ms": budget_ms,
                    "configured_timeout_ms": timeout_ms,
                },
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Latency budget OK",
            metadata={"node": node, "budget_ms": budget_ms},
        )


# ─── Structured Output Enforcement ───

class StructuredOutputGuard(BaseGuardrail):
    """Enforces structured output format (JSON schema) during generation."""

    SCHEMAS = {
        "extraction": {
            "type": "object",
            "required": ["tasks", "meeting_summary", "key_topics"],
            "properties": {
                "tasks": {"type": "array"},
                "meeting_summary": {"type": "string"},
                "key_topics": {"type": "array", "items": {"type": "string"}},
            },
        },
        "verification": {
            "type": "object",
            "required": ["faithfulness_score", "hallucination_score", "completeness_score", "verdict", "reasoning"],
            "properties": {
                "faithfulness_score": {"type": "number", "minimum": 0, "maximum": 1},
                "hallucination_score": {"type": "number", "minimum": 0, "maximum": 1},
                "completeness_score": {"type": "number", "minimum": 0, "maximum": 1},
                "verdict": {"type": "string", "enum": ["PASS", "FAIL", "NEEDS_REVIEW"]},
                "reasoning": {"type": "string"},
            },
        },
        "entity_resolution": {
            "type": "object",
            "required": ["assignee_id", "assignee_name", "confidence", "method"],
            "properties": {
                "assignee_id": {"type": "string"},
                "assignee_name": {"type": "string"},
                "assignee_email": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "method": {"type": "string"},
            },
        },
    }

    def __init__(self, enabled: bool = True):
        super().__init__("structured_output", GuardrailLayer.RUNTIME, enabled)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        node = context.pipeline_node or "default"
        schema = self.SCHEMAS.get(node)

        if not schema:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No schema for node")

        # Check if response_format is set to json_schema in model config
        response_format = context.model_config.get("response_format")
        if response_format and response_format.get("type") == "json_schema":
            return self._create_result(
                GuardrailAction.ALLOW,
                GuardrailSeverity.INFO,
                "JSON schema enforced by model",
                metadata={"schema": node},
            )

        # Otherwise flag that schema enforcement is not configured
        return self._create_result(
            GuardrailAction.FLAG,
            GuardrailSeverity.WARNING,
            f"Structured output not enforced for {node}",
            metadata={"schema": node, "model_config": context.model_config.get("response_format")},
        )


# ─── Runtime Guardrails Pipeline ───

class RuntimeGuardrailsPipeline:
    """Manages all runtime guardrails."""

    def __init__(self):
        self.guardrails = [
            TokenLimitGuard(),
            TemperatureLockGuard(),
            CircuitBreakerGuard(),
            LatencyBudgetGuard(),
            StructuredOutputGuard(),
        ]
        self.nemo = NeMoGuardrailsRuntime()
        self._initialized = False

    async def initialize(self):
        """Initialize all runtime guardrails."""
        if self._initialized:
            return

        await self.nemo.initialize()
        self._initialized = True

    async def run(
        self,
        content: str,
        context: GuardrailContext,
    ) -> List[GuardrailResult]:
        """Run all runtime guardrails."""
        if not self._initialized:
            await self.initialize()

        results = []

        # Run standard guards first (fast, synchronous)
        for guard in self.guardrails:
            if guard.enabled:
                result = await guard.check(content, context)
                results.append(result)

                if result.action in (GuardrailAction.BLOCK, GuardrailAction.FALLBACK):
                    # Stop on blocking actions
                    break

        # Run NeMo if available (can modify output)
        if self.nemo.enabled:
            nemo_result = await self.nemo.check(content, context)
            results.append(nemo_result)

        return results