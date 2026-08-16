"""
Observability Module for PraxisFlow
OpenTelemetry GenAI + Langfuse integration
"""

from app.observability.otel import (
    init_otel,
    shutdown_otel,
    genai_tracer,
    trace_llm_call,
    LLMCallAttributes,
    OTelStructuredLogger,
    get_otel_logger,
)
from app.observability.langfuse import (
    LangfuseClient,
    get_langfuse_client,
    init_langfuse,
)

# Aliases for main.py
init_observability = init_otel
shutdown_observability = shutdown_otel

__all__ = [
    # OTel
    "init_otel",
    "shutdown_otel",
    "genai_tracer",
    "trace_llm_call",
    "LLMCallAttributes",
    "OTelStructuredLogger",
    "get_otel_logger",
    # Langfuse
    "LangfuseClient",
    "get_langfuse_client",
    "init_langfuse",
]