"""
OpenTelemetry GenAI Observability for PraxisFlow
Implements OTel GenAI semantic conventions for LLM tracing, metrics, and logging.
"""

import os
import json
import time
import uuid
import logging
from contextlib import contextmanager
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime

from opentelemetry import trace, metrics, baggage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.b3 import B3MultiFormat
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

from app.core.config import settings

# GenAI Semantic Convention Attributes
GENAI_SYSTEM = "gen_ai.system"
GENAI_REQUEST_MODEL = "gen_ai.request.model"
GENAI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GENAI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GENAI_REQUEST_TOP_P = "gen_ai.request.top_p"
GENAI_REQUEST_FREQUENCY_PENALTY = "gen_ai.request.frequency_penalty"
GENAI_REQUEST_PRESENCE_PENALTY = "gen_ai.request.presence_penalty"
GENAI_REQUEST_STOP_SEQUENCES = "gen_ai.request.stop_sequences"
GENAI_RESPONSE_MODEL = "gen_ai.response.model"
GENAI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GENAI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GENAI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GENAI_USAGE_TOTAL_TOKENS = "gen_ai.usage.total_tokens"
GENAI_AGENT_NAME = "gen_ai.agent.name"
GENAI_AGENT_DESCRIPTION = "gen_ai.agent.description"
GENAI_TOOL_NAME = "gen_ai.tool.name"
GENAI_TOOL_DESCRIPTION = "gen_ai.tool.description"

# PraxisFlow Custom Attributes
PF_TENANT_ID = "praxisflow.tenant_id"
PF_USER_ID = "praxisflow.user_id"
PF_MEETING_ID = "praxisflow.meeting_id"
PF_PIPELINE_NODE = "praxisflow.pipeline_node"
PF_PIPELINE_RUN_ID = "praxisflow.pipeline_run_id"
PF_GUARDRAIL_ACTIONS = "praxisflow.guardrail_actions"
PF_CONFIDENCE_SCORE = "praxisflow.confidence_score"
PF_LATENCY_MS = "praxisflow.latency_ms"
PF_COST_USD = "praxisflow.cost_usd"
PF_EXTRACTION_COUNT = "praxisflow.extraction_count"
PF_VERIFICATION_STATUS = "praxisflow.verification_status"
PF_HALLUCINATION_SCORE = "praxisflow.hallucination_score"
PF_FAITHFULNESS_SCORE = "praxisflow.faithfulness_score"


@dataclass
class LLMCallAttributes:
    """Attributes for an LLM call following GenAI semantic conventions."""
    system: str  # e.g., "groq", "openai", "anthropic"
    model: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop_sequences: List[str] = field(default_factory=list)
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    meeting_id: Optional[str] = None
    pipeline_node: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None


class OTELManager:
    """Manages OpenTelemetry initialization and configuration."""

    def __init__(self):
        self.tracer_provider: Optional[TracerProvider] = None
        self.meter_provider: Optional[MeterProvider] = None
        self.tracer = None
        self.meter = None
        self._initialized = False

    def initialize(self, service_name: str = "praxisflow-api", version: str = "2.0.0"):
        """Initialize OpenTelemetry with GenAI semantic conventions."""

        if self._initialized:
            return

        # Resource with service info
        resource = Resource.create({
            SERVICE_NAME: service_name,
            SERVICE_VERSION: version,
            DEPLOYMENT_ENVIRONMENT: settings.ENVIRONMENT,
            "service.namespace": "praxisflow",
        })

        # Tracer Provider
        self.tracer_provider = TracerProvider(resource=resource)

        # Configure exporters
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

        # OTLP Span Exporter
        otlp_span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        self.tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))

        # Console exporter for development
        if settings.ENVIRONMENT == "development":
            self.tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(self.tracer_provider)
        self.tracer = trace.get_tracer(__name__, version)

        # Meter Provider
        otlp_metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=30000)
        self.meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(self.meter_provider)
        self.meter = metrics.get_meter(__name__, version)

        # Propagators (W3C TraceContext + B3 + Baggage)
        set_global_textmap(CompositePropagator([
            TraceContextTextMapPropagator(),
            B3MultiFormat(),
            W3CBaggagePropagator(),
        ]))

        # Auto-instrumentation
        self._setup_auto_instrumentation()

        self._initialized = True

    def _setup_auto_instrumentation(self):
        """Set up auto-instrumentation for common libraries."""
        try:
            FastAPIInstrumentor.instrument()
        except Exception:
            pass

        try:
            RequestsInstrumentor().instrument()
        except Exception:
            pass

        try:
            RedisInstrumentor().instrument()
        except Exception:
            pass

        try:
            KafkaInstrumentor().instrument()
        except Exception:
            pass

        try:
            Psycopg2Instrumentor().instrument()
        except Exception:
            pass

    def shutdown(self):
        """Shutdown providers gracefully."""
        if self.tracer_provider:
            self.tracer_provider.shutdown()
        if self.meter_provider:
            self.meter_provider.shutdown()
        self._initialized = False


# Global OTEL manager
otel_manager = OTELManager()


class GenAITracer:
    """High-level tracer for GenAI operations with GenAI semantic conventions."""

    def __init__(self):
        self._metrics_created = False

    @property
    def tracer(self):
        return otel_manager.tracer or trace.get_tracer(__name__)

    @property
    def meter(self):
        return otel_manager.meter or metrics.get_meter(__name__)

    def _ensure_metrics(self):
        if not self._metrics_created:
            self._create_metrics()
            self._metrics_created = True

    def _create_metrics(self):
        """Create GenAI metrics instruments."""
        self.llm_request_duration = self.meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="ms",
            description="Duration of LLM API calls",
        )
        self.llm_token_usage = self.meter.create_counter(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Number of tokens used",
        )
        self.llm_request_total = self.meter.create_counter(
            "gen_ai.client.operation.total",
            unit="{request}",
            description="Total number of LLM requests",
        )
        self.llm_error_total = self.meter.create_counter(
            "gen_ai.client.operation.errors",
            unit="{error}",
            description="Total number of LLM errors",
        )
        self.llm_cost = self.meter.create_counter(
            "gen_ai.client.cost.usd",
            unit="USD",
            description="Cost of LLM calls in USD",
        )
        self.guardrail_triggers = self.meter.create_counter(
            "praxisflow.guardrail.triggers",
            unit="{trigger}",
            description="Number of guardrail triggers",
        )
        self.pipeline_duration = self.meter.create_histogram(
            "praxisflow.pipeline.duration",
            unit="ms",
            description="Pipeline execution duration",
        )
        self.extraction_accuracy = self.meter.create_histogram(
            "praxisflow.extraction.accuracy",
            unit="{score}",
            description="Extraction accuracy scores",
        )

    @contextmanager
    def trace_llm_call(self, attrs: LLMCallAttributes):
        """Context manager for tracing an LLM call."""
        span_name = f"llm.{attrs.system}.{attrs.pipeline_node or 'call'}"

        with self.tracer.start_as_current_span(
            span_name,
            kind=SpanKind.CLIENT,
            attributes=self._build_span_attributes(attrs),
        ) as span:
            start_time = time.perf_counter()

            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                self._record_error(attrs, str(e))
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._record_duration(attrs, duration_ms)

    def _build_span_attributes(self, attrs: LLMCallAttributes) -> Dict[str, Any]:
        """Build span attributes following GenAI semantic conventions."""
        span_attrs = {
            GENAI_SYSTEM: attrs.system,
            GENAI_REQUEST_MODEL: attrs.model,
        }

        if attrs.max_tokens:
            span_attrs[GENAI_REQUEST_MAX_TOKENS] = attrs.max_tokens
        if attrs.temperature is not None:
            span_attrs[GENAI_REQUEST_TEMPERATURE] = attrs.temperature
        if attrs.top_p is not None:
            span_attrs[GENAI_REQUEST_TOP_P] = attrs.top_p
        if attrs.frequency_penalty is not None:
            span_attrs[GENAI_REQUEST_FREQUENCY_PENALTY] = attrs.frequency_penalty
        if attrs.presence_penalty is not None:
            span_attrs[GENAI_REQUEST_PRESENCE_PENALTY] = attrs.presence_penalty
        if attrs.stop_sequences:
            span_attrs[GENAI_REQUEST_STOP_SEQUENCES] = attrs.stop_sequences

        # PraxisFlow custom attributes
        if attrs.tenant_id:
            span_attrs[PF_TENANT_ID] = attrs.tenant_id
        if attrs.user_id:
            span_attrs[PF_USER_ID] = attrs.user_id
        if attrs.meeting_id:
            span_attrs[PF_MEETING_ID] = attrs.meeting_id
        if attrs.pipeline_node:
            span_attrs[PF_PIPELINE_NODE] = attrs.pipeline_node
        if attrs.pipeline_run_id:
            span_attrs[PF_PIPELINE_RUN_ID] = attrs.pipeline_run_id
        if attrs.agent_name:
            span_attrs[GENAI_AGENT_NAME] = attrs.agent_name
        if attrs.tool_name:
            span_attrs[GENAI_TOOL_NAME] = attrs.tool_name

        return span_attrs

    def record_llm_response(
        self,
        span,
        attrs: LLMCallAttributes,
        response_model: str,
        finish_reasons: List[str],
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
    ):
        """Record LLM response attributes on span."""
        self._ensure_metrics()
        span.set_attributes({
            GENAI_RESPONSE_MODEL: response_model,
            GENAI_RESPONSE_FINISH_REASONS: finish_reasons,
            GENAI_USAGE_INPUT_TOKENS: input_tokens,
            GENAI_USAGE_OUTPUT_TOKENS: output_tokens,
            GENAI_USAGE_TOTAL_TOKENS: input_tokens + output_tokens,
            PF_COST_USD: cost_usd,
        })

        # Record metrics
        labels = {
            "system": attrs.system,
            "model": attrs.model,
            "tenant_id": attrs.tenant_id or "unknown",
            "pipeline_node": attrs.pipeline_node or "unknown",
        }

        self.llm_token_usage.add(input_tokens, labels | {"token_type": "input"})
        self.llm_token_usage.add(output_tokens, labels | {"token_type": "output"})
        self.llm_request_total.add(1, labels)
        if cost_usd > 0:
            self.llm_cost.add(cost_usd, labels)

    def record_guardrail_action(self, attrs: LLMCallAttributes, action: str, guardrail_name: str):
        """Record a guardrail trigger."""
        self._ensure_metrics()
        span = trace.get_current_span()
        if span and span.is_recording():
            current = span.attributes.get(PF_GUARDRAIL_ACTIONS, [])
            current.append(f"{guardrail_name}:{action}")
            span.set_attribute(PF_GUARDRAIL_ACTIONS, current)

        labels = {
            "tenant_id": attrs.tenant_id or "unknown",
            "pipeline_node": attrs.pipeline_node or "unknown",
            "guardrail": guardrail_name,
            "action": action,
        }
        self.guardrail_triggers.add(1, labels)

    def record_pipeline_metrics(
        self,
        pipeline_run_id: str,
        tenant_id: str,
        meeting_id: str,
        duration_ms: float,
        extraction_count: int,
        verification_status: str,
        hallucination_score: Optional[float] = None,
        faithfulness_score: Optional[float] = None,
    ):
        """Record pipeline execution metrics."""
        self._ensure_metrics()
        if not self._metrics_created:
            return
        labels = {
            "tenant_id": tenant_id,
            "verification_status": verification_status,
        }

        self.pipeline_duration.record(duration_ms, labels)
        self.extraction_accuracy.record(extraction_count, labels)

        if hallucination_score is not None:
            self.extraction_accuracy.record(hallucination_score, labels | {"metric": "hallucination"})
        if faithfulness_score is not None:
            self.extraction_accuracy.record(faithfulness_score, labels | {"metric": "faithfulness"})

    def log_pipeline_step(self, step: str, status: str, **kwargs):
        """Log pipeline step execution with trace context."""
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            span.add_event(f"pipeline.{step}.{status}", attributes=kwargs)
        
        # Also log via structured logger
        logger = logging.getLogger("praxisflow.pipeline")
        context = self._get_trace_context() if hasattr(self, '_get_trace_context') else {}
        logger.info(
            f"Pipeline step: {step} - {status}",
            extra={**context, "pipeline_step": step, "status": status, **kwargs}
        )

    def _get_trace_context(self) -> Dict[str, str]:
        """Extract current trace context for logging."""
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.get_span_context().trace_id:
            trace_id = format(span.get_span_context().trace_id, '032x')
            span_id = format(span.get_span_context().span_id, '016x')
            return {"trace_id": trace_id, "span_id": span_id}
        return {}

    def _record_duration(self, attrs: LLMCallAttributes, duration_ms: float):
        self._ensure_metrics()
        if not self._metrics_created:
            return
        labels = {
            "system": attrs.system,
            "model": attrs.model,
            "tenant_id": attrs.tenant_id or "unknown",
            "pipeline_node": attrs.pipeline_node or "unknown",
        }
        self.llm_request_duration.record(duration_ms, labels)

    def _record_error(self, attrs: LLMCallAttributes, error: str):
        self._ensure_metrics()
        if not self._metrics_created:
            return
        labels = {
            "system": attrs.system,
            "model": attrs.model,
            "tenant_id": attrs.tenant_id or "unknown",
            "pipeline_node": attrs.pipeline_node or "unknown",
            "error_type": type(error).__name__,
        }
        self.llm_error_total.add(1, labels)


# Global tracer instance
genai_tracer = GenAITracer()


def init_otel(service_name: str = "praxisflow-api", version: str = "2.0.0"):
    """Initialize OpenTelemetry. Call once at app startup."""
    otel_manager.initialize(service_name, version)
    return genai_tracer


def shutdown_otel():
    """Shutdown OpenTelemetry. Call at app shutdown."""
    otel_manager.shutdown()


# ─── Decorators for easy tracing ───

def trace_llm_call(
    system: str,
    model: str,
    pipeline_node: str = None,
    **llm_kwargs
):
    """Decorator to trace an LLM call function."""
    def decorator(func: Callable):
        async def async_wrapper(*args, **kwargs):
            # Extract context from args/kwargs
            tenant_id = kwargs.get("tenant_id")
            user_id = kwargs.get("user_id")
            meeting_id = kwargs.get("meeting_id")
            pipeline_run_id = kwargs.get("pipeline_run_id")

            attrs = LLMCallAttributes(
                system=system,
                model=model,
                pipeline_node=pipeline_node,
                tenant_id=tenant_id,
                user_id=user_id,
                meeting_id=meeting_id,
                pipeline_run_id=pipeline_run_id,
                max_tokens=llm_kwargs.get("max_tokens"),
                temperature=llm_kwargs.get("temperature"),
                top_p=llm_kwargs.get("top_p"),
            )

            with genai_tracer.trace_llm_call(attrs) as span:
                result = await func(*args, **kwargs)

                # Record response if result has usage info
                if hasattr(result, "usage"):
                    genai_tracer.record_llm_response(
                        span=span,
                        attrs=attrs,
                        response_model=model,
                        finish_reasons=getattr(result, "finish_reasons", ["stop"]),
                        input_tokens=result.usage.prompt_tokens,
                        output_tokens=result.usage.completion_tokens,
                        cost_usd=getattr(result, "cost_usd", 0.0),
                    )

                return result

        def sync_wrapper(*args, **kwargs):
            # Similar for sync functions
            tenant_id = kwargs.get("tenant_id")
            user_id = kwargs.get("user_id")
            meeting_id = kwargs.get("meeting_id")
            pipeline_run_id = kwargs.get("pipeline_run_id")

            attrs = LLMCallAttributes(
                system=system,
                model=model,
                pipeline_node=pipeline_node,
                tenant_id=tenant_id,
                user_id=user_id,
                meeting_id=meeting_id,
                pipeline_run_id=pipeline_run_id,
                max_tokens=llm_kwargs.get("max_tokens"),
                temperature=llm_kwargs.get("temperature"),
                top_p=llm_kwargs.get("top_p"),
            )

            with genai_tracer.trace_llm_call(attrs) as span:
                result = func(*args, **kwargs)

                if hasattr(result, "usage"):
                    genai_tracer.record_llm_response(
                        span=span,
                        attrs=attrs,
                        response_model=model,
                        finish_reasons=getattr(result, "finish_reasons", ["stop"]),
                        input_tokens=result.usage.prompt_tokens,
                        output_tokens=result.usage.completion_tokens,
                        cost_usd=getattr(result, "cost_usd", 0.0),
                    )

                return result

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ─── Structured Logging with OTel Context ───

class OTelStructuredLogger:
    """Structured logger that includes OTel trace context."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def _get_trace_context(self) -> Dict[str, str]:
        """Extract current trace context for logging."""
        span = trace.get_current_span()
        if span and span.get_span_context().trace_id:
            trace_id = format(span.get_span_context().trace_id, '032x')
            span_id = format(span.get_span_context().span_id, '016x')
            return {"trace_id": trace_id, "span_id": span_id}
        return {}

    def log_llm_call(self, attrs: LLMCallAttributes, event: str, **kwargs):
        """Log LLM call with trace context."""
        context = self._get_trace_context()
        self.logger.info(
            event,
            extra={
                **context,
                "gen_ai.system": attrs.system,
                "gen_ai.request.model": attrs.model,
                "praxisflow.tenant_id": attrs.tenant_id,
                "praxisflow.meeting_id": attrs.meeting_id,
                "praxisflow.pipeline_node": attrs.pipeline_node,
                **kwargs,
            }
        )

    def log_guardrail_trigger(self, guardrail: str, action: str, **kwargs):
        """Log guardrail trigger."""
        context = self._get_trace_context()
        self.logger.warning(
            f"Guardrail triggered: {guardrail} -> {action}",
            extra={**context, "guardrail": guardrail, "action": action, **kwargs}
        )

    def log_pipeline_step(self, step: str, status: str, **kwargs):
        """Log pipeline step execution."""
        context = self._get_trace_context()
        self.logger.info(
            f"Pipeline step: {step} - {status}",
            extra={**context, "pipeline_step": step, "status": status, **kwargs}
        )


# Convenience function
def get_otel_logger(name: str) -> OTelStructuredLogger:
    return OTelStructuredLogger(name)