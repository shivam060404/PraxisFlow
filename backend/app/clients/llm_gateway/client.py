"""
LLM Gateway Client - Unified interface for all LLM providers via LiteLLM.
"""

import os
import json
import logging
import hashlib
from typing import Dict, Any, Optional, List, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import asynccontextmanager

import litellm
from litellm import acompletion, aembedding, aimage_generation
from pydantic import BaseModel, Field

from app.core.config import settings
from app.observability.otel import genai_tracer, LLMCallAttributes, trace_llm_call
from app.ai.guardrails.manager import (
    guardrails_manager,
)
from app.clients.llm_gateway.routing import ModelRouter, RoutingPolicy
from app.clients.llm_gateway.budgets import TokenBudgetManager
from app.clients.llm_gateway.caching import SemanticCache
from app.clients.llm_gateway.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class GatewayResponse:
    """Standardized gateway response."""
    content: str
    model: str
    usage: Dict[str, int]
    cost_usd: float
    latency_ms: float
    finish_reason: str
    cached: bool = False
    guardrail_results: List[Dict] = field(default_factory=list)


@dataclass
class EmbeddingResponse:
    """Standardized embedding response."""
    embeddings: List[List[float]]
    model: str
    usage: Dict[str, int]
    cost_usd: float


class LLMGatewayClient:
    """
    Unified LLM Gateway Client.
    
    Handles:
    - Model routing with fallback chains
    - Token budget enforcement
    - Semantic caching
    - Guardrails integration
    - Cost tracking
    - Circuit breaker pattern
    """

    def __init__(self):
        self.router = ModelRouter()
        self.budget_manager = TokenBudgetManager()
        self.cache = SemanticCache()
        self.circuit_breaker = CircuitBreaker()
        self._initialized = False

    async def initialize(self):
        """Initialize gateway components."""
        if self._initialized:
            return

        # Configure LiteLLM
        litellm.set_verbose = settings.ENVIRONMENT == "development"
        litellm.drop_params = True

        # Set API keys from settings
        if settings.GROQ_API_KEY:
            os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", None)
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key

        # Initialize components
        await self.router.initialize()
        await self.budget_manager.initialize()
        await self.cache.initialize()
        await self.circuit_breaker.initialize()

        self._initialized = True
        logger.info("LLM Gateway initialized")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        pipeline_node: str,
        tenant_id: str,
        user_id: str,
        meeting_id: Optional[str] = None,
        pipeline_run_id: Optional[str] = None,
        model_override: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
        use_cache: bool = True,
        stream: bool = False,
    ) -> GatewayResponse:
        """
        Execute a chat completion with full gateway features.
        """
        if not self._initialized:
            await self.initialize()

        # Determine model and routing
        routing = self.router.get_route(pipeline_node)
        model = model_override or routing.primary
        fallback_models = routing.fallback

        # Build model config for guardrails
        model_config = {
            "model": model,
            "temperature": routing.temperature if temperature is None else temperature,
            "max_tokens": routing.max_tokens if max_tokens is None else max_tokens,
            "timeout_ms": routing.timeout_ms,
            "response_format": response_format,
        }

        # Prepare context for guardrails
        context = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "meeting_id": meeting_id,
            "pipeline_node": pipeline_node,
            "pipeline_run_id": pipeline_run_id,
            "model_config": model_config,
            "transcript_context": "\n".join(str(message.get("content", "")) for message in messages),
        }

        # Run controls in this client rather than relying on optional LiteLLM
        # callback semantics. This path is shared by direct dev calls and the
        # authenticated production proxy.
        prompt_text = "\n".join(str(message.get("content", "")) for message in messages)
        precheck = await guardrails_manager.pre_call_check(prompt_text, context)
        if not precheck.get("allowed", False):
            raise LLMGatewayError(f"Input blocked by guardrails: {precheck.get('reason', 'blocked')}")
        if precheck.get("prompt") != prompt_text:
            replacement = precheck["prompt"]
            messages = [dict(message) for message in messages]
            for message in reversed(messages):
                if message.get("role") == "user":
                    message["content"] = replacement
                    break
        runtime = await guardrails_manager.runtime_check(prompt_text, context)
        if not runtime.get("allowed", False):
            raise LLMGatewayError(f"Runtime guardrail blocked request: {runtime.get('reason', 'blocked')}")

        # Check cache first
        if use_cache and not stream:
            cache_key = self._generate_cache_key(messages, model_config, tenant_id)
            cached = await self.cache.get(cache_key)
            if cached:
                output_check = await guardrails_manager.post_call_check(cached.get("content", ""), context)
                if not output_check.get("allowed", False):
                    raise LLMGatewayError(f"Cached output blocked by guardrails: {output_check.get('reason', 'blocked')}")
                cached["content"] = output_check["response"]
                cached["guardrail_results"] = precheck.get("results", []) + output_check.get("results", [])
                logger.info(f"Cache hit for {pipeline_node} (tenant: {tenant_id})")
                cached["cached"] = True
                return GatewayResponse(**cached)

        # Check token budget
        estimated_tokens = self._estimate_tokens(messages, model_config.get("max_tokens", 4096))
        budget_ok = await self.budget_manager.check_budget(tenant_id, estimated_tokens)
        if not budget_ok:
            raise BudgetExceededError(f"Token budget exceeded for tenant {tenant_id}")

        # Execute with fallback chain
        last_error = None
        models_to_try = [model] + fallback_models

        for attempt_model in models_to_try:
            # Check circuit breaker
            if await self.circuit_breaker.is_open(attempt_model):
                logger.warning(f"Circuit open for {attempt_model}, trying fallback")
                continue

            model_config["model"] = attempt_model
            context["model_config"] = model_config

            try:
                start_time = datetime.utcnow()

                # OTel tracing
                attrs = LLMCallAttributes(
                    system=self._get_provider(attempt_model),
                    model=attempt_model,
                    pipeline_node=pipeline_node,
                    tenant_id=tenant_id,
                    meeting_id=meeting_id,
                    pipeline_run_id=pipeline_run_id,
                    max_tokens=model_config.get("max_tokens"),
                    temperature=model_config.get("temperature"),
                )

                with genai_tracer.trace_llm_call(attrs) as span:
                    response = await self._make_completion(
                        messages=messages,
                        model=attempt_model,
                        model_config=model_config,
                        context=context,
                        stream=stream,
                    )

                    output_check = await guardrails_manager.post_call_check(
                        response.choices[0].message.content or "",
                        context,
                    )
                    if not output_check.get("allowed", False):
                        raise LLMGatewayError(
                            f"Model output blocked by guardrails: {output_check.get('reason', 'blocked')}"
                        )
                    response.choices[0].message.content = output_check["response"]

                    latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

                    # Record usage
                    usage = response.usage
                    cost = self._calculate_cost(attempt_model, usage.prompt_tokens, usage.completion_tokens)

                    genai_tracer.record_llm_response(
                        span=span,
                        attrs=attrs,
                        response_model=attempt_model,
                        finish_reasons=[response.choices[0].finish_reason] if response.choices else ["stop"],
                        input_tokens=usage.prompt_tokens,
                        output_tokens=usage.completion_tokens,
                        cost_usd=cost,
                    )

                    # Record budget usage
                    await self.budget_manager.record_usage(tenant_id, usage.total_tokens)

                    # Build response
                    result = GatewayResponse(
                        content=response.choices[0].message.content or "",
                        model=attempt_model,
                        usage={
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "total_tokens": usage.total_tokens,
                        },
                        cost_usd=cost,
                        latency_ms=latency_ms,
                        finish_reason=response.choices[0].finish_reason if response.choices else "stop",
                        guardrail_results=precheck.get("results", []) + runtime.get("results", []) + output_check.get("results", []),
                    )

                    # Cache successful response
                    if use_cache and not stream:
                        await self.cache.set(cache_key, result.__dict__)

                    # Record success for circuit breaker
                    await self.circuit_breaker.record_success(attempt_model)

                    logger.info(f"Completion successful: {attempt_model} ({latency_ms:.0f}ms, ${cost:.4f})")
                    return result

            except Exception as e:
                last_error = e
                logger.warning(f"Model {attempt_model} failed: {e}")
                await self.circuit_breaker.record_failure(attempt_model)

        # All models failed
        raise LLMGatewayError(f"All models failed. Last error: {last_error}")

    async def _make_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        model_config: Dict[str, Any],
        context: Dict[str, Any],
        stream: bool = False,
    ):
        """Make the actual LLM completion call."""
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": model_config.get("temperature", 0.1),
            "max_tokens": model_config.get("max_tokens", 4096),
            "timeout": model_config.get("timeout_ms", 30000) / 1000,
            "stream": stream,
            "metadata": {key: value for key, value in context.items() if key != "transcript_context"},
        }

        if settings.LLM_GATEWAY_URL:
            # Production routes provider calls through the separately deployed
            # LiteLLM proxy. Direct provider calls remain a local-dev option.
            kwargs["api_base"] = settings.LLM_GATEWAY_URL.rstrip("/") + "/v1"
            kwargs["api_key"] = settings.LLM_GATEWAY_MASTER_KEY

        if model_config.get("response_format"):
            kwargs["response_format"] = model_config["response_format"]

        return await acompletion(**kwargs)

    async def embeddings(
        self,
        texts: List[str],
        tenant_id: str,
        user_id: str,
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        """Generate embeddings."""
        if not self._initialized:
            await self.initialize()

        model = model or "openai/text-embedding-3-large"

        # Check budget
        estimated = sum(len(t) // 4 for t in texts)
        budget_ok = await self.budget_manager.check_budget(tenant_id, estimated)
        if not budget_ok:
            raise BudgetExceededError(f"Token budget exceeded for tenant {tenant_id}")

        embedding_kwargs = {
            "model": model,
            "input": texts,
            "metadata": {"tenant_id": tenant_id, "user_id": user_id},
        }
        if settings.LLM_GATEWAY_URL:
            embedding_kwargs["api_base"] = settings.LLM_GATEWAY_URL.rstrip("/") + "/v1"
            embedding_kwargs["api_key"] = settings.LLM_GATEWAY_MASTER_KEY
        response = await aembedding(**embedding_kwargs)

        usage = response.usage
        cost = self._calculate_cost(model, usage.prompt_tokens, 0)

        await self.budget_manager.record_usage(tenant_id, usage.total_tokens)

        return EmbeddingResponse(
            embeddings=[d.embedding for d in response.data],
            model=model,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "total_tokens": usage.total_tokens,
            },
            cost_usd=cost,
        )

    def _get_provider(self, model: str) -> str:
        """Extract provider from model string."""
        if "/" in model:
            return model.split("/")[0]
        if model.startswith("gpt") or model.startswith("text-embedding"):
            return "openai"
        if model.startswith("claude"):
            return "anthropic"
        if model.startswith("llama") or "groq" in model.lower():
            return "groq"
        return "unknown"

    def _generate_cache_key(self, messages: List[Dict], model_config: Dict, tenant_id: str = "") -> str:
        """Generate semantic cache key."""
        content = tenant_id + json.dumps(messages, sort_keys=True) + json.dumps(model_config, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _estimate_tokens(self, messages: List[Dict], max_tokens: int) -> int:
        """Estimate token count for request."""
        text = " ".join(m.get("content", "") for m in messages)
        return len(text) // 4 + max_tokens

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in USD."""
        # Simplified pricing - in production use a pricing service
        pricing = {
            "groq/llama-3.3-70b-versatile": {"input": 0.0001, "output": 0.0001},
            "openai/gpt-4o": {"input": 0.005, "output": 0.015},
            "openai/gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "anthropic/claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
            "openai/text-embedding-3-large": {"input": 0.00013, "output": 0},
        }
        rates = pricing.get(model, {"input": 0.001, "output": 0.001})
        return (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000


class BudgetExceededError(Exception):
    pass


class LLMGatewayError(Exception):
    pass


# Global instance
_gateway_client: Optional[LLMGatewayClient] = None


async def get_gateway_client() -> LLMGatewayClient:
    """Get or create global gateway client."""
    global _gateway_client
    if _gateway_client is None:
        _gateway_client = LLMGatewayClient()
        await _gateway_client.initialize()
    return _gateway_client
