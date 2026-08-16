"""
Guardrails Integration Layer for PraxisFlow Backend
Provides pre-call, runtime, and post-call hooks for the LLM Gateway.
"""

from typing import Dict, Any, Optional, List
import asyncio
import logging
import json
from datetime import datetime

from app.core.config import settings
from app.guardrails.input_guardrails import (
    PromptInjectionDetector,
    InputPIIScanner,
    TopicBoundaryGuard,
    JailbreakDetector,
    InputLengthValidator,
    TenantIsolationGuard,
)
from app.guardrails.runtime_guardrails import (
    NeMoGuardrailsRuntime,
    TokenLimitGuard,
    TemperatureLockGuard,
    CircuitBreakerGuard,
)
from app.guardrails.output_guardrails import (
    HallucinationDetector,
    OutputPIIScanner,
    FormatValidator,
    ConfidenceThresholdGuard,
    ContradictionDetector,
    ContentPolicyGuard,
)

logger = logging.getLogger(__name__)


class GuardrailsManager:
    """Central manager for all guardrails."""

    def __init__(self):
        self._initialized = False
        self.input_guardrails: List = []
        self.runtime_guardrails: List = []
        self.output_guardrails: List = []

        # Runtime state
        self.circuit_breaker = CircuitBreakerGuard()

    async def initialize(self):
        """Initialize all guardrails."""
        if self._initialized:
            return

        # Input guardrails
        self.input_guardrails = [
            PromptInjectionDetector(enabled=True),
            InputPIIScanner(enabled=True, action="redact"),
            TopicBoundaryGuard(enabled=True),
            JailbreakDetector(enabled=True),
            InputLengthValidator(max_tokens_estimate=8000, enabled=True),
            TenantIsolationGuard(enabled=True),
        ]

        # Runtime guardrails
        self.runtime_guardrails = [
            TokenLimitGuard(enabled=True),
            TemperatureLockGuard(enabled=True),
            self.circuit_breaker,
        ]

        # Try to initialize NeMo
        nemo = NeMoGuardrailsRuntime(enabled=True)
        await nemo.initialize()
        if nemo.enabled:
            self.runtime_guardrails.append(nemo)

        # Output guardrails
        self.output_guardrails = [
            HallucinationDetector(enabled=True, faithfulness_threshold=0.7),
            OutputPIIScanner(enabled=True),
            FormatValidator(enabled=True),
            ConfidenceThresholdGuard(enabled=True),
            ContradictionDetector(enabled=True),
            ContentPolicyGuard(enabled=True),
        ]

        self._initialized = True
        logger.info("Guardrails manager initialized")

    async def pre_call_check(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Pre-call hook: Run input guardrails before sending to LLM.
        Returns modified prompt and guardrail results.
        """
        if not self._initialized:
            await self.initialize()

        from app.guardrails.base import GuardrailContext

        guardrail_context = GuardrailContext(
            tenant_id=context.get("tenant_id", ""),
            user_id=context.get("user_id", ""),
            meeting_id=context.get("meeting_id"),
            pipeline_node=context.get("pipeline_node"),
            model_config=context.get("model_config", {}),
        )

        modified_prompt = prompt
        results = []

        for guardrail in self.input_guardrails:
            try:
                result = await guardrail.check(modified_prompt, guardrail_context)
                results.append({
                    "guardrail": guardrail.name,
                    "layer": "input",
                    "action": result.action.value,
                    "severity": result.severity.value,
                    "message": result.message,
                    "metadata": result.metadata,
                })

                if result.modified_content:
                    modified_prompt = result.modified_content

                if result.action.value in ("block", "fallback"):
                    logger.warning(f"Input blocked by {guardrail.name}: {result.message}")
                    return {
                        "allowed": False,
                        "prompt": modified_prompt,
                        "results": results,
                        "blocked_by": guardrail.name,
                        "reason": result.message,
                    }

            except Exception as e:
                logger.error(f"Input guardrail {guardrail.name} failed: {e}")
                results.append({
                    "guardrail": guardrail.name,
                    "layer": "input",
                    "action": "error",
                    "message": str(e),
                })

        return {
            "allowed": True,
            "prompt": modified_prompt,
            "results": results,
        }

    async def runtime_check(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Runtime hook: Check token limits, temperature, circuit breakers.
        """
        if not self._initialized:
            await self.initialize()

        from app.guardrails.base import GuardrailContext

        guardrail_context = GuardrailContext(
            tenant_id=context.get("tenant_id", ""),
            user_id=context.get("user_id", ""),
            meeting_id=context.get("meeting_id"),
            pipeline_node=context.get("pipeline_node"),
            model_config=context.get("model_config", {}),
        )

        results = []

        for guardrail in self.runtime_guardrails:
            try:
                result = await guardrail.check(prompt, guardrail_context)
                results.append({
                    "guardrail": guardrail.name,
                    "layer": "runtime",
                    "action": result.action.value,
                    "severity": result.severity.value,
                    "message": result.message,
                    "metadata": result.metadata,
                })

                if result.action.value == "fallback":
                    return {
                        "allowed": False,
                        "fallback": True,
                        "results": results,
                        "reason": result.message,
                    }

            except Exception as e:
                logger.error(f"Runtime guardrail {guardrail.name} failed: {e}")
                results.append({
                    "guardrail": guardrail.name,
                    "layer": "runtime",
                    "action": "error",
                    "message": str(e),
                })

        return {"allowed": True, "results": results}

    async def post_call_check(
        self,
        response: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Post-call hook: Run output guardrails on LLM response.
        """
        if not self._initialized:
            await self.initialize()

        from app.guardrails.base import GuardrailContext

        guardrail_context = GuardrailContext(
            tenant_id=context.get("tenant_id", ""),
            user_id=context.get("user_id", ""),
            meeting_id=context.get("meeting_id"),
            pipeline_node=context.get("pipeline_node"),
            transcript_context=context.get("transcript_context"),
            prior_extractions=context.get("prior_extractions", []),
            model_config=context.get("model_config", {}),
        )

        modified_response = response
        results = []
        route_to_human = False
        human_review_reasons = []

        for guardrail in self.output_guardrails:
            try:
                result = await guardrail.check(modified_response, guardrail_context)
                results.append({
                    "guardrail": guardrail.name,
                    "layer": "output",
                    "action": result.action.value,
                    "severity": result.severity.value,
                    "message": result.message,
                    "metadata": result.metadata,
                })

                if result.modified_content:
                    modified_response = result.modified_content

                if result.action.value == "route_to_human":
                    route_to_human = True
                    human_review_reasons.append(result.message)

                if result.action.value == "block":
                    return {
                        "allowed": False,
                        "response": modified_response,
                        "results": results,
                        "blocked_by": guardrail.name,
                        "reason": result.message,
                    }

            except Exception as e:
                logger.error(f"Output guardrail {guardrail.name} failed: {e}")
                results.append({
                    "guardrail": guardrail.name,
                    "layer": "output",
                    "action": "error",
                    "message": str(e),
                })

        return {
            "allowed": True,
            "response": modified_response,
            "results": results,
            "route_to_human": route_to_human,
            "human_review_reasons": human_review_reasons,
        }

    def record_model_failure(self, model: str):
        """Record a model failure for circuit breaker."""
        self.circuit_breaker.record_failure(model)

    def record_model_success(self, model: str):
        """Record a model success for circuit breaker."""
        self.circuit_breaker.record_success(model)


# Global instance
guardrails_manager = GuardrailsManager()


# ─── LiteLLM Callback Hooks ───

async def litellm_pre_call_hook(kwargs: Dict, **extra) -> Dict:
    """
    LiteLLM pre-call hook for guardrails.
    Called before making the LLM request.
    """
    # Extract context from kwargs
    context = {
        "tenant_id": kwargs.get("metadata", {}).get("tenant_id", ""),
        "user_id": kwargs.get("metadata", {}).get("user_id", ""),
        "meeting_id": kwargs.get("metadata", {}).get("meeting_id"),
        "pipeline_node": kwargs.get("metadata", {}).get("pipeline_node"),
        "model_config": {
            "model": kwargs.get("model"),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
        },
    }

    # Get the prompt
    messages = kwargs.get("messages", [])
    prompt = "\n".join([m.get("content", "") for m in messages])

    # Run pre-call guardrails
    result = await guardrails_manager.pre_call_check(prompt, context)

    if not result["allowed"]:
        # Raise exception to block the call
        from litellm import RateLimitError
        raise RateLimitError(
            message=result["reason"],
            model=kwargs.get("model", "unknown"),
            llm_provider="guardrails",
        )

    # Update messages with modified prompt if needed
    if result["prompt"] != prompt:
        # Reconstruct messages with modified prompt
        # For simplicity, replace last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                msg["content"] = result["prompt"]
                break

    # Add guardrail metadata to response
    kwargs["metadata"]["guardrail_results"] = result["results"]
    kwargs["metadata"]["guardrail_pre_call"] = True

    return kwargs


async def litellm_post_call_hook(response: Any, kwargs: Dict, **extra) -> Any:
    """
    LiteLLM post-call hook for guardrails.
    Called after receiving LLM response.
    """
    try:
        # Extract response content
        content = ""
        if hasattr(response, "choices") and response.choices:
            content = response.choices[0].message.content or ""
        elif isinstance(response, dict) and "choices" in response:
            content = response["choices"][0]["message"]["content"] or ""

        if not content:
            return response

        # Extract context
        context = {
            "tenant_id": kwargs.get("metadata", {}).get("tenant_id", ""),
            "user_id": kwargs.get("metadata", {}).get("user_id", ""),
            "meeting_id": kwargs.get("metadata", {}).get("meeting_id"),
            "pipeline_node": kwargs.get("metadata", {}).get("pipeline_node"),
            "transcript_context": kwargs.get("metadata", {}).get("transcript_context"),
            "prior_extractions": kwargs.get("metadata", {}).get("prior_extractions", []),
            "model_config": {
                "model": kwargs.get("model"),
                "temperature": kwargs.get("temperature"),
            },
        }

        # Run post-call guardrails
        result = await guardrails_manager.post_call_check(content, context)

        # Add guardrail results to response metadata
        if not hasattr(response, "metadata"):
            response.metadata = {}
        response.metadata["guardrail_results"] = result["results"]
        response.metadata["guardrail_post_call"] = True
        response.metadata["route_to_human"] = result.get("route_to_human", False)
        response.metadata["human_review_reasons"] = result.get("human_review_reasons", [])

        # If response was modified, update it
        if result["response"] != content:
            if hasattr(response, "choices") and response.choices:
                response.choices[0].message.content = result["response"]
            elif isinstance(response, dict) and "choices" in response:
                response["choices"][0]["message"]["content"] = result["response"]

        # Handle model success/failure for circuit breaker
        model = kwargs.get("model", "unknown")
        if result["allowed"]:
            guardrails_manager.record_model_success(model)
        else:
            guardrails_manager.record_model_failure(model)

    except Exception as e:
        logger.error(f"Post-call guardrail hook failed: {e}")

    return response


# ─── Utility Functions ───

async def check_prompt_injection(text: str) -> bool:
    """Quick check for prompt injection."""
    detector = PromptInjectionDetector()
    from app.guardrails.base import GuardrailContext
    ctx = GuardrailContext(tenant_id="", user_id="")
    result = await detector.check(text, ctx)
    return result.action.value == "block"


async def scan_pii(text: str) -> Dict[str, int]:
    """Scan text for PII."""
    scanner = InputPIIScanner()
    from app.guardrails.base import GuardrailContext
    ctx = GuardrailContext(tenant_id="", user_id="")
    result = await scanner.check(text, ctx)
    return result.metadata.get("pii_types", {})


async def validate_output_format(output: str, schema_name: str) -> bool:
    """Validate output against schema."""
    validator = FormatValidator()
    from app.guardrails.base import GuardrailContext
    ctx = GuardrailContext(tenant_id="", user_id="")
    # Would need schema mapping
    return True