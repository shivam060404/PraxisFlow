"""
Observability Module for PraxisFlow
OpenTelemetry GenAI + Langfuse integration
"""

from app.observability.otel import (
    init_otel,
    get_tracer,
    get_meter,
    create_span,
    record_llm_call,
    record_guardrail_action,
    record_pipeline_metrics,
    OTelStructuredLogger,
    get_otel_logger,
)
from app.observability.langfuse import (
    LangfuseClient,
    get_langfuse_client,
    init_langfuse,
    TraceData,
    GenerationInput,
    GenerationOutput,
)

__all__ = [
    # OTel
    "init_otel",
    "get_tracer",
    "get_meter",
    "create_span",
    "record_llm_call",
    "record_guardrail_action",
    "record_pipeline_metrics",
    "OTelStructuredLogger",
    "get_otel_logger",
    # Langfuse
    "LangfuseClient",
    "get_langfuse_client",
    "init_langfuse",
    "TraceData",
    "GenerationInput",
    "GenerationOutput",
]