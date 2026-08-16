"""
Langfuse Integration for LLM Observability
Provides tracing, evaluations, and cost tracking for PraxisFlow LLM calls.
"""

import os
import uuid
import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager

from langfuse import Langfuse


from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TraceData:
    """Data for creating a Langfuse trace."""
    name: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    input: Optional[Any] = None
    output: Optional[Any] = None


@dataclass
class GenerationInput:
    """Input for a generation."""
    prompt: Union[str, List[Dict[str, str]]]
    model: str
    model_parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationOutput:
    """Output from a generation."""
    completion: str
    usage: Dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
    model: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    cost_usd: Optional[float] = None


class LangfuseClient:
    """Wrapper around Langfuse SDK for PraxisFlow."""

    def __init__(self):
        self.client: Optional[Langfuse] = None
        self._initialized = False

    def initialize(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
    ):
        """Initialize Langfuse client."""
        if self._initialized:
            return

        public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        host = host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        if not public_key or not secret_key:
            logger.warning("Langfuse keys not configured, skipping initialization")
            return

        try:
            self.client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                debug=settings.ENVIRONMENT == "development",
            )
            self._initialized = True
            logger.info("Langfuse client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse: {e}")

    def is_ready(self) -> bool:
        return self._initialized and self.client is not None

    def create_trace(self, trace_data: TraceData) -> str:
        """Create a new trace and return trace_id."""
        if not self.is_ready():
            return str(uuid.uuid4())

        try:
            trace = self.client.trace(
                name=trace_data.name,
                user_id=trace_data.user_id,
                session_id=trace_data.session_id,
                metadata=trace_data.metadata,
                tags=trace_data.tags,
                input=trace_data.input,
                output=trace_data.output,
            )
            return trace.id
        except Exception as e:
            logger.error(f"Failed to create trace: {e}")
            return str(uuid.uuid4())

    def create_generation(
        self,
        trace_id: str,
        name: str,
        input_data: GenerationInput,
        output_data: Optional[GenerationOutput] = None,
        parent_observation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a generation (LLM call) within a trace."""
        if not self.is_ready():
            return str(uuid.uuid4())

        try:
            generation = self.client.generation(
                trace_id=trace_id,
                name=name,
                model=input_data.model,
                model_parameters=input_data.model_parameters,
                input=input_data.prompt,
                metadata={**(input_data.metadata), **(metadata or {})},
                parent_observation_id=parent_observation_id,
            )

            if output_data:
                generation.end(
                    output=output_data.completion,
                    usage=output_data.usage,
                    cost=output_data.cost_usd,
                    metadata=output_data.metadata,
                    finish_reason=output_data.finish_reason,
                )

            return generation.id
        except Exception as e:
            logger.error(f"Failed to create generation: {e}")
            return str(uuid.uuid4())

    def update_generation(
        self,
        trace_id: str,
        generation_id: str,
        output_data: GenerationOutput,
    ):
        """Update an existing generation with output."""
        if not self.is_ready():
            return

        try:
            self.client.generation(
                trace_id=trace_id,
                id=generation_id,
            ).end(
                output=output_data.completion,
                usage=output_data.usage,
                cost=output_data.cost_usd,
                metadata=output_data.metadata,
                finish_reason=output_data.finish_reason,
            )
        except Exception as e:
            logger.error(f"Failed to update generation: {e}")

    def score_generation(
        self,
        trace_id: str,
        generation_id: str,
        name: str,
        value: float,
        comment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Add a score/evaluation to a generation."""
        if not self.is_ready():
            return

        try:
            self.client.score(
                trace_id=trace_id,
                observation_id=generation_id,
                name=name,
                value=value,
                comment=comment,
                metadata=metadata,
            )
        except Exception as e:
            logger.error(f"Failed to score generation: {e}")

    def create_span(
        self,
        trace_id: str,
        name: str,
        input_data: Optional[Any] = None,
        output_data: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_observation_id: Optional[str] = None,
    ) -> str:
        """Create a span (non-LLM operation) within a trace."""
        if not self.is_ready():
            return str(uuid.uuid4())

        try:
            span = self.client.span(
                trace_id=trace_id,
                name=name,
                input=input_data,
                output=output_data,
                metadata=metadata,
                parent_observation_id=parent_observation_id,
            )
            return span.id
        except Exception as e:
            logger.error(f"Failed to create span: {e}")
            return str(uuid.uuid4())

    def end_span(
        self,
        trace_id: str,
        span_id: str,
        output_data: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """End a span."""
        if not self.is_ready():
            return

        try:
            self.client.span(
                trace_id=trace_id,
                id=span_id,
            ).end(
                output=output_data,
                metadata=metadata,
            )
        except Exception as e:
            logger.error(f"Failed to end span: {e}")

    def flush(self):
        """Flush buffered events."""
        if self.is_ready():
            self.client.flush()

    def shutdown(self):
        """Shutdown client."""
        if self.is_ready():
            self.client.shutdown()
            self._initialized = False


# Global client instance
_langfuse_client = LangfuseClient()


def get_langfuse_client() -> LangfuseClient:
    """Get the global Langfuse client."""
    return _langfuse_client


def init_langfuse(
    public_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    host: Optional[str] = None,
):
    """Initialize Langfuse client."""
    _langfuse_client.initialize(public_key, secret_key, host)


# ─── Convenience Functions for PraxisFlow ───

def trace_pipeline_run(
    tenant_id: str,
    meeting_id: str,
    pipeline_run_id: str,
    user_id: Optional[str] = None,
) -> str:
    """Create a trace for a pipeline run."""
    client = get_langfuse_client()
    trace_data = TraceData(
        name="praxisflow.pipeline.run",
        user_id=user_id,
        session_id=tenant_id,
        metadata={
            "tenant_id": tenant_id,
            "meeting_id": meeting_id,
            "pipeline_run_id": pipeline_run_id,
            "service": "praxisflow",
        },
        tags=["pipeline", "extraction", tenant_id],
    )
    return client.create_trace(trace_data)


def trace_llm_generation(
    trace_id: str,
    pipeline_node: str,
    model: str,
    prompt: Union[str, List[Dict]],
    model_params: Dict[str, Any],
    completion: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None,
    cost_usd: Optional[float] = None,
    finish_reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parent_observation_id: Optional[str] = None,
) -> str:
    """Trace an LLM generation within a pipeline trace."""
    client = get_langfuse_client()

    input_data = GenerationInput(
        prompt=prompt,
        model=model,
        model_parameters=model_params,
        metadata={"pipeline_node": pipeline_node},
    )

    output_data = None
    if completion:
        output_data = GenerationOutput(
            completion=completion,
            usage=usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            model=model,
            cost_usd=cost_usd,
            finish_reason=finish_reason,
            metadata=metadata or {},
        )

    return client.create_generation(
        trace_id=trace_id,
        name=f"llm.{pipeline_node}",
        input_data=input_data,
        output_data=output_data,
        parent_observation_id=parent_observation_id,
        metadata={"pipeline_node": pipeline_node, **(metadata or {})},
    )


def score_extraction(
    trace_id: str,
    generation_id: str,
    faithfulness: float,
    hallucination: float,
    completeness: float,
    verdict: str,
    reasoning: str,
):
    """Score an extraction generation with quality metrics."""
    client = get_langfuse_client()

    client.score_generation(
        trace_id=trace_id,
        generation_id=generation_id,
        name="faithfulness",
        value=faithfulness,
        comment=f"Faithfulness score: {faithfulness:.2f}",
        metadata={"verdict": verdict, "reasoning": reasoning},
    )

    client.score_generation(
        trace_id=trace_id,
        generation_id=generation_id,
        name="hallucination",
        value=hallucination,
        comment=f"Hallucination score: {hallucination:.2f} (lower is better)",
    )

    client.score_generation(
        trace_id=trace_id,
        generation_id=generation_id,
        name="completeness",
        value=completeness,
        comment=f"Completeness score: {completeness:.2f}",
    )

    # Overall verdict score
    verdict_score = 1.0 if verdict == "PASS" else (0.5 if verdict == "NEEDS_REVIEW" else 0.0)
    client.score_generation(
        trace_id=trace_id,
        generation_id=generation_id,
        name="verdict",
        value=verdict_score,
        comment=f"Verification verdict: {verdict}",
        metadata={"verdict": verdict, "reasoning": reasoning},
    )


def trace_guardrail_action(
    trace_id: str,
    guardrail_name: str,
    action: str,
    severity: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Trace a guardrail trigger as a span."""
    client = get_langfuse_client()

    span_id = client.create_span(
        trace_id=trace_id,
        name=f"guardrail.{guardrail_name}",
        input_data={"action": action, "severity": severity, "message": message},
        metadata={"guardrail": guardrail_name, "action": action, **(metadata or {})},
    )

    client.end_span(
        trace_id=trace_id,
        span_id=span_id,
        output_data={"triggered": True},
        metadata={"guardrail": guardrail_name, "action": action},
    )


def trace_human_review(
    trace_id: str,
    task_id: str,
    reviewer_id: str,
    decision: str,  # APPROVE, REJECT, MODIFY
    feedback: Optional[str] = None,
    modified_output: Optional[str] = None,
):
    """Trace a human review action."""
    client = get_langfuse_client()

    span_id = client.create_span(
        trace_id=trace_id,
        name="human.review",
        input_data={
            "task_id": task_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "feedback": feedback,
        },
        metadata={"task_id": task_id, "type": "human_review"},
    )

    client.end_span(
        trace_id=trace_id,
        span_id=span_id,
        output_data={
            "decision": decision,
            "modified_output": modified_output,
        },
    )


# ─── Context Manager for Pipeline Tracing ───

class PipelineTraceContext:
    """Context manager for tracing a complete pipeline run."""

    def __init__(
        self,
        tenant_id: str,
        meeting_id: str,
        pipeline_run_id: str,
        user_id: Optional[str] = None,
    ):
        self.tenant_id = tenant_id
        self.meeting_id = meeting_id
        self.pipeline_run_id = pipeline_run_id
        self.user_id = user_id
        self.trace_id: Optional[str] = None
        self.client = get_langfuse_client()
        self.node_generations: Dict[str, str] = {}

    def __enter__(self) -> "PipelineTraceContext":
        self.trace_id = trace_pipeline_run(
            tenant_id=self.tenant_id,
            meeting_id=self.meeting_id,
            pipeline_run_id=self.pipeline_run_id,
            user_id=self.user_id,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.trace_id and exc_type:
            # Mark trace as error
            self.client.create_span(
                trace_id=self.trace_id,
                name="pipeline.error",
                input_data={"error": str(exc_val)},
                metadata={"error_type": exc_type.__name__},
            )
        if self.trace_id:
            self.client.flush()

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
        generation_id = trace_llm_generation(
            trace_id=self.trace_id,
            pipeline_node=node_name,
            model=model,
            prompt=prompt,
            model_params=model_params,
            completion=completion,
            usage=usage,
            cost_usd=cost_usd,
            finish_reason=finish_reason,
            metadata=metadata,
        )
        self.node_generations[node_name] = generation_id
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
        """Score a pipeline node's output."""
        if node_name in self.node_generations:
            score_extraction(
                trace_id=self.trace_id,
                generation_id=self.node_generations[node_name],
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
        trace_guardrail_action(
            trace_id=self.trace_id,
            guardrail_name=guardrail_name,
            action=action,
            severity=severity,
            message=message,
            metadata=metadata,
        )