"""
Base classes and types for AI Guardrails
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class GuardrailAction(str, Enum):
    """Actions a guardrail can take."""
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"
    FLAG = "flag"
    RETRY = "retry"
    FALLBACK = "fallback"
    ROUTE_TO_HUMAN = "route_to_human"


class GuardrailLayer(str, Enum):
    """Layer in the guardrail pipeline."""
    INPUT = "input"
    RUNTIME = "runtime"
    OUTPUT = "output"


class GuardrailSeverity(str, Enum):
    """Severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    action: GuardrailAction
    layer: GuardrailLayer
    guardrail_name: str
    severity: GuardrailSeverity
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    modified_content: Optional[str] = None
    confidence: float = 1.0
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class GuardrailContext:
    """Context passed to all guardrails."""
    tenant_id: str
    user_id: str
    meeting_id: Optional[str] = None
    pipeline_node: Optional[str] = None
    transcript_context: Optional[str] = None
    prior_extractions: List[Dict] = field(default_factory=list)
    model_config: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class BaseGuardrail(ABC):
    """Base class for all guardrails."""

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
    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        """Check content and return result."""
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

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name}, layer={self.layer.value}, enabled={self.enabled})"


class GuardrailPipeline:
    """Runs a sequence of guardrails."""

    def __init__(self, guardrails: List[BaseGuardrail]):
        self.guardrails = guardrails

    async def run(
        self,
        content: str,
        context: GuardrailContext,
        stop_on_block: bool = True,
    ) -> List[GuardrailResult]:
        """Run all guardrails in sequence."""
        results = []

        for guardrail in self.guardrails:
            if not guardrail.enabled:
                continue

            result = await guardrail.check(content, context)
            results.append(result)

            # Use modified content for next guardrail if provided
            if result.modified_content:
                content = result.modified_content

            if stop_on_block and result.action == GuardrailAction.BLOCK:
                break

        return results

    def get_final_action(self, results: List[GuardrailResult]) -> GuardrailAction:
        """Determine final action from all results."""
        # Priority: BLOCK > FALLBACK > ROUTE_TO_HUMAN > RETRY > FLAG > ALLOW
        priority = {
            GuardrailAction.BLOCK: 5,
            GuardrailAction.FALLBACK: 4,
            GuardrailAction.ROUTE_TO_HUMAN: 3,
            GuardrailAction.RETRY: 2,
            GuardrailAction.FLAG: 1,
            GuardrailAction.ALLOW: 0,
            GuardrailAction.REDACT: 0,  # Redact is not blocking
        }

        max_priority = max(priority.get(r.action, 0) for r in results)
        for action, p in priority.items():
            if p == max_priority:
                return action

        return GuardrailAction.ALLOW