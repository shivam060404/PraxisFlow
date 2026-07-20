"""
Main Observability Module for PraxisFlow
Integrates OpenTelemetry GenAI tracing, Langfuse, and structured logging.
"""

import logging
import structlog
from contextlib import contextmanager
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from app.observability.langfuse_client import (
    LangfuseClient,
    get_langfuse_client,
    init_langfuse,
    PipelineTraceContext,
    trace_pipeline_run,
    trace_llm_generation,
    score_extraction,
    trace_guardrail_action,
    trace_human_review,
)
from app.observability.otel import (
    init_otel,
    shutdown_otel,
    genai_tracer,
    GenAITracer,
    LLMCallAttributes,
    trace_llm_call,
    OTelStructuredLogger,
)

logger = logging.getLogger(__name__)


# ─── Configuration ───

@dataclass
class ObservabilityConfig:
    """Configuration for observability stack."""
    # OpenTelemetry
    otel_enabled: bool = True
    otel_service_name: str = "praxisflow-api"
    otel_service_version: str = "2.0.0"
    otel_exporter_endpoint: str = "http://otel-collector:4317"

    # Langfuse
    langfuse_enabled: bool = True
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or console

    # Metrics
    metrics_enabled: bool = True
    metrics_port: int = 9090

    # Tracing
    trace_sample_rate: float = 1.0  # 1.0 = 100%
    trace_sample_rate_errors: float = 1.0


# ─── Global State ───

_observability_initialized = False
_otel_tracer: Optional[GenAITracer] = None
_langfuse_client: Optional[LangfuseClient] = None
_structlog_logger: Optional[structlog.BoundLogger] = None


# ─── Initialization ───

def init_observability(config: Optional[ObservabilityConfig] = None) -> Dict[str, Any]:
    """
    Initialize the complete observability stack.
    Returns dict with initialized components.
    """
    global _observability_initialized, _otel_tracer, _langfuse_client, _structlog_logger

    if _observability_initialized:
        logger.warning("Observability already initialized")
        return _get_components()

    config = config or ObservabilityConfig()

    # 1. Configure structured logging
    _configure_logging(config)

    # 2. Initialize OpenTelemetry
    if config.otel_enabled:
        _otel_tracer = init_otel(config.otel_service_name, config.otel_service_version)
        logger.info("OpenTelemetry initialized")

    # 3. Initialize Langfuse
    if config.langfuse_enabled:
        init_langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_host,
        )
        _langfuse_client = get_langfuse_client()
        logger.info("Langfuse initialized")

    _observability_initialized = True
    logger.info("Observability stack initialized")

    return _get_components()


def _configure_logging(config: ObservabilityConfig):
    """Configure structlog with OTel context."""
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if config.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set stdlib log level
    logging.getLogger().setLevel(getattr(logging, config.log_level.upper()))


def _get_components() -> Dict[str, Any]:
    return {
        "otel_tracer": _otel_tracer,
        "langfuse_client": _langfuse_client,
        "logger": get_otel_logger(),
    }


def shutdown_observability():
    """Shutdown all observability components."""
    global _observability_initialized

    if _otel_tracer:
        shutdown_otel()

    if _langfuse_client:
        _langfuse_client.shutdown()

    _observability_initialized = False
    logger.info("Observability stack shutdown")


# ─── Logger Access ───

def get_otel_logger(name: str = "praxisflow") -> structlog.BoundLogger:
    """Get structured logger with OTel context."""
    global _structlog_logger
    if _structlog_logger is None:
        _structlog_logger = structlog.get_logger(name)
    return _structlog_logger


# ─── High-Level Tracing Functions ───

@contextmanager
def trace_pipeline(
    tenant_id: str,
    meeting_id: str,
    pipeline_run_id: str,
    user_id: Optional[str] = None,
):
    """Context manager for tracing a complete pipeline run with both OTel and Langfuse."""
    # OTel tracing
    pipeline_attrs = LLMCallAttributes(
        system="praxisflow",
        model="pipeline",
        pipeline_node="pipeline",
        tenant_id=tenant_id,
        meeting_id=meeting_id,
        pipeline_run_id=pipeline_run_id,
        user_id=user_id,
    )

    with genai_tracer.trace_llm_call(pipeline_attrs) as otel_span:
        # Langfuse tracing
        langfuse_ctx = PipelineTraceContext(
            tenant_id=tenant_id,
            meeting_id=meeting_id,
            pipeline_run_id=pipeline_run_id,
            user_id=user_id,
        )

        try:
            yield PipelineTracer(otel_span, langfuse_ctx)
        except Exception as e:
            # Record error in both systems
            otel_span.record_exception(e)
            otel_span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))

            langfuse_ctx.client.create_span(
                trace_id=langfuse_ctx.trace_id,
                name="pipeline.error",
                input_data={"error": str(e)},
                metadata={"error_type": type(e).__name__},
            )
            raise


@dataclass
class PipelineTracer:
    """Combined tracer for pipeline operations."""
    otel_span: Any
    langfuse: PipelineTraceContext

    def trace_node(
        self,
        node_name: str,
        model: str,
        prompt: Union[str, List[Dict]],
        model_params: Dict[str, Any],
        completion: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        cost_usd: Optional[float] = None,
        finish_reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Trace a pipeline node's LLM call."""
        # OTel
        node_attrs = LLMCallAttributes(
            system="praxisflow",
            model=model,
            pipeline_node=node_name,
            tenant_id=self.langfuse.tenant_id,
            meeting_id=self.langfuse.meeting_id,
            pipeline_run_id=self.langfuse.pipeline_run_id,
            max_tokens=model_params.get("max_tokens"),
            temperature=model_params.get("temperature"),
            top_p=model_params.get("top_p"),
        )

        # For OTel, we record the call after completion
        if completion and usage:
            genai_tracer.record_llm_response(
                span=self.otel_span,
                attrs=node_attrs,
                response_model=model,
                finish_reasons=[finish_reason] if finish_reason else ["stop"],
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                cost_usd=cost_usd or 0.0,
            )

        # Langfuse
        generation_id = self.langfuse.trace_node(
            node_name=node_name,
            model=model,
            prompt=prompt,
            model_params=model_params,
            completion=completion,
            usage=usage,
            cost_usd=cost_usd,
            finish_reason=finish_reason,
            metadata=metadata,
        )

        return generation_id

    def score_node(
        self,
        node_name: str,
        faithfulness: float,
        hallucination: float,
        completeness: float,
        verdict: str,
        reasoning: str,
    ):
        """Score a node's output."""
        self.langfuse.score_node(
            node_name=node_name,
            faithfulness=faithfulness,
            hallucination=hallucination,
            completeness=completeness,
            verdict=verdict,
            reasoning=reasoning,
        )

    def trace_guardrail(
        self,
        guardrail_name: str,
        action: str,
        severity: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Trace a guardrail trigger."""
        # OTel - add to current span
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_actions = current_span.attributes.get(PF_GUARDRAIL_ACTIONS, [])
            current_actions.append(f"{guardrail_name}:{action}")
            current_span.set_attribute(PF_GUARDRAIL_ACTIONS, current_actions)

        # Langfuse
        self.langfuse.trace_guardrail(
            guardrail_name=guardrail_name,
            action=action,
            severity=severity,
            message=message,
            metadata=metadata,
        )

    def record_metrics(
        self,
        duration_ms: float,
        extraction_count: int,
        verification_status: str,
        hallucination_score: Optional[float] = None,
        faithfulness_score: Optional[float] = None,
    ):
        """Record pipeline metrics."""
        genai_tracer.record_pipeline_execution(
            pipeline_run_id=self.langfuse.pipeline_run_id,
            tenant_id=self.langfuse.tenant_id,
            meeting_id=self.langfuse.meeting_id,
            duration_ms=duration_ms,
            extraction_count=extraction_count,
            verification_status=verification_status,
            hallucination_score=hallucination_score,
            faithfulness_score=faithfulness_score,
        )


# ─── Decorators for Common Patterns ───

def trace_extraction_node(node_name: str, model: str):
    """Decorator for tracing extraction pipeline nodes."""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            # Extract context
            tenant_id = kwargs.get("tenant_id")
            meeting_id = kwargs.get("meeting_id")
            pipeline_run_id = kwargs.get("pipeline_run_id")

            # Get langfuse context if available
            langfuse_ctx = kwargs.get("_langfuse_ctx")

            with genai_tracer.trace_llm_call(LLMCallAttributes(
                system="groq" if "groq" in model.lower() else "openai",
                model=model,
                pipeline_node=node_name,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                pipeline_run_id=pipeline_run_id,
            )) as span:
                result = await func(*args, **kwargs)

                # Record result
                if hasattr(result, "usage"):
                    genai_tracer.record_llm_response(
                        span=span,
                        attrs=LLMCallAttributes(
                            system="groq" if "groq" in model.lower() else "openai",
                            model=model,
                            pipeline_node=node_name,
                            tenant_id=tenant_id,
                            meeting_id=meeting_id,
                            pipeline_run_id=pipeline_run_id,
                        ),
                        response_model=model,
                        finish_reasons=getattr(result, "finish_reasons", ["stop"]),
                        input_tokens=result.usage.prompt_tokens,
                        output_tokens=result.usage.completion_tokens,
                        cost_usd=getattr(result, "cost_usd", 0.0),
                    )

                return result

        return async_wrapper
    return decorator


# ─── Health Check ───

def get_observability_health() -> Dict[str, Any]:
    """Get health status of observability components."""
    health = {
        "otel_initialized": _otel_tracer is not None,
        "langfuse_initialized": _langfuse_client is not None and _langfuse_client.is_ready(),
        "logging_configured": _structlog_logger is not None,
    }

    if _langfuse_client and _langfuse_client.is_ready():
        health["langfuse_flush_pending"] = True  # Would check actual queue

    return health


# ─── Exports ───

__all__ = [
    # Config
    "ObservabilityConfig",
    # Initialization
    "init_observability",
    "shutdown_observability",
    "get_observability_health",
    # Logging
    "get_otel_logger",
    # Tracing
    "trace_pipeline",
    "PipelineTracer",
    "trace_extraction_node",
    # Langfuse
    "LangfuseClient",
    "get_langfuse_client",
    "init_langfuse",
    "PipelineTraceContext",
    "trace_pipeline_run",
    "trace_llm_generation",
    "score_extraction",
    "trace_guardrail_action",
    "trace_human_review",
    # OTel
    "GenAITracer",
    "LLMCallAttributes",
    "trace_llm_call",
    "OTelStructuredLogger",
]