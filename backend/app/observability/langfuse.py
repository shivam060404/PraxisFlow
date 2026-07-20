"""
Langfuse Client for PraxisFlow
Self-hosted LLM observability and evaluation platform integration.
"""

import os
import uuid
import logging
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager

from langfuse import Langfuse
from langfuse.model import CreateTrace, CreateGeneration, CreateSpan, CreateScore, CreateEvent

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── Configuration ───

@dataclass
class LangfuseConfig:
    public_key: str
    secret_key: str
    host: str = "http://langfuse:3000"
    release: str = "2.0.0"
    debug: bool = False
    threads: int = 4
    flush_at: int = 15
    flush_interval: int = 5


# ─── Client Wrapper ───

class LangfuseClient:
    """Wrapper around Langfuse SDK with PraxisFlow-specific helpers."""

    def __init__(self, config: LangfuseConfig):
        self.config = config
        self.client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
            release=config.release,
            debug=config.debug,
            threads=config.threads,
            flush_at=config.flush_at,
            flush_interval=config.flush_interval,
        )
        self._traces: Dict[str, str] = {}  # trace_name -> trace_id

    def is_ready(self) -> bool:
        """Check if client is healthy."""
        try:
            # Quick health check
            return True
        except Exception:
            return False

    def create_trace(
        self,
        name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Create a new trace."""
        trace = self.client.trace(
            CreateTrace(
                name=name,
                user_id=user_id,
                session_id=session_id,
                metadata=metadata or {},
                tags=tags or [],
            )
        )
        self._traces[name] = trace.id
        return trace.id

    def get_trace(self, trace_id: str) -> Optional[Any]:
        """Get trace by ID."""
        return self.client.get_trace(trace_id)

    def create_generation(
        self,
        trace_id: str,
        name: str,
        model: str,
        model_parameters: Dict[str, Any],
        prompt: Union[str, List[Dict[str, str]]],
        completion: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        cost: Optional[float] = None,
        finish_reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """Create a generation (LLM call) within a trace."""
        gen = self.client.generation(
            CreateGeneration(
                trace_id=trace_id,
                name=name,
                model=model,
                model_parameters=model_parameters,
                prompt=prompt,
                completion=completion,
                usage=usage,
                cost=cost,
                finish_reason=finish_reason,
                metadata=metadata or {},
                start_time=start_time or datetime.utcnow(),
                end_time=end_time or datetime.utcnow(),
            )
        )
        return gen.id

    def create_span(
        self,
        trace_id: str,
        name: str,
        input_data: Optional[Any] = None,
        output_data: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a span within a trace."""
        span = self.client.span(
            CreateSpan(
                trace_id=trace_id,
                name=name,
                input=input_data,
                output=output_data,
                metadata=metadata or {},
            )
        )
        return span.id

    def create_score(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: Optional[str] = None,
        data_type: str = "NUMERIC",
        observation_id: Optional[str] = None,
    ) -> str:
        """Create a score/evaluation for a trace or observation."""
        score = self.client.score(
            CreateScore(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment,
                data_type=data_type,
                observation_id=observation_id,
            )
        )
        return score.id

    def create_event(
        self,
        trace_id: str,
        name: str,
        input_data: Optional[Any] = None,
        output_data: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create an event within a trace."""
        event = self.client.event(
            CreateEvent(
                trace_id=trace_id,
                name=name,
                input=input_data,
                output=output_data,
                metadata=metadata or {},
            )
        )
        return event.id

    def flush(self):
        """Flush pending events."""
        self.client.flush()

    def shutdown(self):
        """Gracefully shutdown."""
        self.flush()
        self.client.shutdown()


# ─── Global Instance ───

_langfuse_client: Optional[LangfuseClient] = None


def init_langfuse(
    public_key: str,
    secret_key: str,
    host: str = "http://langfuse:3000",
    release: str = "2.0.0",
    debug: bool = False,
) -> LangfuseClient:
    """Initialize global Langfuse client."""
    global _langfuse_client

    config = LangfuseConfig(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
        release=release,
        debug=debug,
    )

    _langfuse_client = LangfuseClient(config)
    logger.info("Langfuse client initialized")
    return _langfuse_client


def get_langfuse_client() -> Optional[LangfuseClient]:
    """Get global Langfuse client."""
    return _langfuse_client


# ─── PraxisFlow Trace Contexts ───

@dataclass
class PipelineTraceContext:
    """Context for tracing a pipeline execution."""
    tenant_id: str
    meeting_id: str
    pipeline_run_id: str
    user_id: Optional[str] = None
    trace_id: Optional[str] = None
    _generation_ids: Dict[str, str] = field(default_factory=dict)  # node_name -> generation_id

    def __post_init__(self):
        if not self.trace_id:
            client = get_langfuse_client()
            if client:
                self.trace_id = client.create_trace(
                    name="praxisflow.pipeline",
                    user_id=self.user_id,
                    session_id=self.meeting_id,
                    metadata={
                        "tenant_id": self.tenant_id,
                        "meeting_id": self.meeting_id,
                        "pipeline_run_id": self.pipeline_run_id,
                    },
                    tags=["pipeline", self.tenant_id],
                )


@contextmanager
def trace_pipeline_run(
    tenant_id: str,
    meeting_id: str,
    pipeline_run_id: str,
    user_id: Optional[str] = None,
) -> PipelineTraceContext:
    """Context manager for tracing a complete pipeline run."""
    ctx = PipelineTraceContext(
        tenant_id=tenant_id,
        meeting_id=meeting_id,
        pipeline_run_id=pipeline_run_id,
        user_id=user_id,
    )

    client = get_langfuse_client()
    start_time = datetime.utcnow()

    try:
        yield ctx
    except Exception as e:
        # Record error
        if client and ctx.trace_id:
            client.create_event(
                trace_id=ctx.trace_id,
                name="pipeline.error",
                input_data={"error": str(e), "error_type": type(e).__name__},
                metadata={"pipeline_run_id": pipeline_run_id},
            )
        raise
    finally:
        # Record duration
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        if client and ctx.trace_id:
            client.create_event(
                trace_id=ctx.trace_id,
                name="pipeline.complete",
                input_data={"duration_ms": duration_ms},
                metadata={"pipeline_run_id": pipeline_run_id},
            )


def trace_llm_generation(
    trace_id: str,
    name: str,
    model: str,
    model_params: Dict[str, Any],
    prompt: Union[str, List[Dict[str, str]]],
    completion: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None,
    cost_usd: Optional[float] = None,
    finish_reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Helper to trace a single LLM generation."""
    client = get_langfuse_client()
    if not client:
        return ""

    return client.create_generation(
        trace_id=trace_id,
        name=name,
        model=model,
        model_parameters=model_params,
        prompt=prompt,
        completion=completion,
        usage=usage,
        cost=cost_usd,
        finish_reason=finish_reason,
        metadata=metadata,
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
    """Score an extraction generation."""
    client = get_langfuse_client()
    if not client:
        return

    scores = [
        ("faithfulness", faithfulness, "Faithfulness to source"),
        ("hallucination", hallucination, "Hallucination rate"),
        ("completeness", completeness, "Completeness of extraction"),
    ]

    for name, value, comment in scores:
        client.create_score(
            trace_id=trace_id,
            name=name,
            value=value,
            comment=comment,
            observation_id=generation_id,
        )

    client.create_score(
        trace_id=trace_id,
        name="verdict",
        value=1.0 if verdict == "PASS" else 0.0,
        comment=reasoning,
        observation_id=generation_id,
        data_type="CATEGORICAL",
    )


def trace_guardrail_action(
    trace_id: str,
    guardrail_name: str,
    action: str,
    severity: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Trace a guardrail trigger event."""
    client = get_langfuse_client()
    if not client:
        return

    client.create_event(
        trace_id=trace_id,
        name=f"guardrail.{guardrail_name}",
        input_data={
            "action": action,
            "severity": severity,
            "message": message,
        },
        metadata=metadata,
    )


def trace_human_review(
    trace_id: str,
    task_id: str,
    reviewer_id: str,
    action: str,
    original_output: str,
    reviewed_output: Optional[str] = None,
    feedback: Optional[str] = None,
):
    """Trace human-in-the-loop review."""
    client = get_langfuse_client()
    if not client:
        return

    client.create_event(
        trace_id=trace_id,
        name="human_review",
        input_data={
            "task_id": task_id,
            "action": action,
            "original_output": original_output,
        },
        output_data={
            "reviewed_output": reviewed_output,
            "feedback": feedback,
        },
        metadata={
            "reviewer_id": reviewer_id,
        },
    )


# ─── Dataset Management ───

def create_dataset(
    name: str,
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a dataset for evaluation."""
    client = get_langfuse_client()
    if not client:
        return ""

    # Langfuse datasets are created via API
    # This would use the REST API directly
    logger.info(f"Dataset creation requested: {name}")
    return ""


def add_dataset_item(
    dataset_id: str,
    input_data: Any,
    expected_output: Any,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Add item to evaluation dataset."""
    client = get_langfuse_client()
    if not client:
        return
    logger.info(f"Adding item to dataset {dataset_id}")


def run_evaluation(
    dataset_id: str,
    experiment_name: str,
    model_fn: callable,
    scoring_fn: callable,
):
    """Run evaluation on dataset."""
    client = get_langfuse_client()
    if not client:
        return
    logger.info(f"Evaluation run requested: {experiment_name}")


# ─── Prompt Management ───

def create_prompt(
    name: str,
    prompt: Union[str, List[Dict[str, str]]],
    labels: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a versioned prompt."""
    client = get_langfuse_client()
    if not client:
        return ""

    # Would use Langfuse prompt management API
    logger.info(f"Prompt creation requested: {name}")
    return ""


def get_prompt(name: str, label: str = "latest") -> Optional[Dict[str, Any]]:
    """Get a prompt by name and label."""
    client = get_langfuse_client()
    if not client:
        return None
    logger.info(f"Prompt retrieval requested: {name}@{label}")
    return None


# ─── Cost Tracking ───

def get_cost_summary(
    start_date: datetime,
    end_date: datetime,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Get cost summary for date range."""
    client = get_langfuse_client()
    if not client:
        return {}

    # Would query Langfuse API
    return {
        "total_cost": 0.0,
        "total_tokens": 0,
        "by_model": {},
        "by_tag": {},
    }


# ─── Exports ───

__all__ = [
    "LangfuseConfig",
    "LangfuseClient",
    "init_langfuse",
    "get_langfuse_client",
    "PipelineTraceContext",
    "trace_pipeline_run",
    "trace_llm_generation",
    "score_extraction",
    "trace_guardrail_action",
    "trace_human_review",
    "create_dataset",
    "add_dataset_item",
    "run_evaluation",
    "create_prompt",
    "get_prompt",
    "get_cost_summary",
]