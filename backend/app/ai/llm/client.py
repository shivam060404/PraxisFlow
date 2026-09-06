"""AI-facing facade for the shared LLM gateway client.

Provider access remains implemented in ``app.clients.llm_gateway``. This
module keeps AI package imports stable without duplicating gateway logic.
"""

from app.clients.llm_gateway.client import (
    EmbeddingResponse,
    GatewayResponse,
    LLMGatewayClient,
    LLMGatewayError,
    BudgetExceededError,
    get_gateway_client,
)

__all__ = [
    "EmbeddingResponse",
    "GatewayResponse",
    "LLMGatewayClient",
    "LLMGatewayError",
    "BudgetExceededError",
    "get_gateway_client",
]
