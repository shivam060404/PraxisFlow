"""AI-facing LLM contracts.

The implementation boundary is ``app.clients.llm_gateway``; this package
provides a stable AI namespace for callers that work at the AI layer.
"""

from app.ai.llm.client import (
    BudgetExceededError,
    EmbeddingResponse,
    GatewayResponse,
    LLMGatewayClient,
    LLMGatewayError,
    get_gateway_client,
)
from app.ai.llm.routing import ModelRouter, RoutingPolicy
from app.clients.llm_gateway import (
    BudgetConfig,
    CircuitBreaker,
    CircuitBreakerConfig,
    SemanticCache,
    TokenBudgetManager,
)

__all__ = [
    "BudgetConfig",
    "BudgetExceededError",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "EmbeddingResponse",
    "GatewayResponse",
    "LLMGatewayClient",
    "ModelRouter",
    "RoutingPolicy",
    "SemanticCache",
    "TokenBudgetManager",
    "get_gateway_client",
]
