"""
Base classes and types for AI Guardrails
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod


class GuardrailAction(str, Enum):
    """Possible actions a guardrail can take."""
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"
    FLAG = "flag"
    RETRY = "retry"
    FALLBACK = "fallback"
    ROUTE_TO_HUMAN = "route_to_human"


class GuardrailLayer(str, Enum):
    """Three-layer guardrail architecture."""
    INPUT = "input"       # Pre-LLM: injection, PII, topic, jailbreak
    RUNTIME = "runtime"   # During LLM: NeMo, token limits, temp lock, circuit breaker
    OUTPUT = "output"     # Post-LLM: hallucination, PII leak, format, confidence


class GuardrailSeverity(str, Enum):
    """Severity levels for guardrail events."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class GuardrailResult:
    """Result of a single guardrail check."""
    action: GuardrailAction
    layer: GuardrailLayer
    guardrail_name: str
    severity: GuardrailSeverity
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    modified_content: Optional[str] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "layer": self.layer.value,
            "guardrail_name": self.guardrail_name,
            "severity": self.severity.value,
            "message": self.message,
            "metadata": self.metadata,
            "has_modified_content": self.modified_content is not None,
            "confidence": self.confidence,
        }


@dataclass
class GuardrailContext:
    """Context passed to all guardrails."""
    tenant_id: str
    user_id: str
    meeting_id: Optional[str] = None
    pipeline_node: Optional[str] = None  # extraction, verification, entity_resolution, etc.
    transcript_context: Optional[str] = None  # For grounding checks
    prior_extractions: List[Dict] = field(default_factory=list)
    model_config: Dict[str, Any] = field(default_factory=dict)  # temperature, model, etc.
    request_id: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "meeting_id": self.meeting_id,
            "pipeline_node": self.pipeline_node,
            "has_transcript_context": self.transcript_context is not None,
            "prior_extractions_count": len(self.prior_extractions),
            "model_config": self.model_config,
            "request_id": self.request_id,
        }


class BaseGuardrail(ABC):
    """Abstract base class for all guardrails."""

    def __init__(
        self,
        name: str,
        layer: GuardrailLayer,
        enabled: bool = True,
    ):
        self.name = name
        self.layer = layer
        self.enabled = enabled

    @abstractmethod
    async def check(
        self,
        content: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        """
        Check content against this guardrail.

        Args:
            content: The content to check (prompt for input, response for output)
            context: Context including tenant, user, meeting, pipeline node, etc.

        Returns:
            GuardrailResult with action, severity, and any modifications
        """
        pass

    def _create_result(
        self,
        action: GuardrailAction,
        severity: GuardrailSeverity,
        message: str,
        metadata: Dict = None,
        modified_content: str = None,
        confidence: float = 1.0,
    ) -> GuardrailResult:
        """Helper to create result with common fields."""
        return GuardrailResult(
            action=action,
            layer=self.layer,
            guardrail_name=self.name,
            severity=severity,
            message=message,
            metadata=metadata or {},
            modified_content=modified_content,
            confidence=confidence,
        )