"""
Output Guardrails for PraxisFlow
Post-LLM validation: hallucination detection, PII leak detection, format validation,
confidence thresholding, contradiction detection, content policy.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
import re
import json
import logging
from abc import ABC, abstractmethod

from app.guardrails import BaseGuardrail, GuardrailAction, GuardrailLayer, GuardrailResult, GuardrailContext, GuardrailSeverity
from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── Output PII Scanner ───

class OutputPIIScanner(BaseGuardrail):
    """Scans LLM output for PII leakage."""

    PII_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone": r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        "api_key": r"(sk|pk)_[a-zA-Z0-9]{32,}",
        "aws_key": r"AKIA[0-9A-Z]{16}",
        "github_token": r"gh[pousr]_[a-zA-Z0-9]{36,}",
        "jwt_token": r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*",
    }

    def __init__(self, enabled: bool = True, action: GuardrailAction = GuardrailAction.REDACT):
        super().__init__("output_pii_scanner", GuardrailLayer.OUTPUT, enabled)
        self.action = action
        self.compiled_patterns = {k: re.compile(v) for k, v in self.PII_PATTERNS.items()}

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Guardrail disabled")

        detected = {}
        redacted_content = content

        for pii_type, pattern in self.compiled_patterns.items():
            matches = pattern.findall(content)
            if matches:
                detected[pii_type] = len(matches)
                if self.action == GuardrailAction.REDACT:
                    redacted_content = pattern.sub(f"[REDACTED_{pii_type.upper()}]", redacted_content)

        if detected:
            logger.warning(f"PII detected in output for tenant {context.tenant_id}: {detected}")
            return self._create_result(
                action=self.action,
                severity=GuardrailSeverity.WARNING,
                message=f"PII leaked in output: {detected}",
                metadata={"pii_types": detected, "redacted": self.action == GuardrailAction.REDACT},
                modified_content=redacted_content if self.action == GuardrailAction.REDACT else None,
                confidence=0.95,
            )

        return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No PII in output")


# ─── Format Validator ───

class FormatValidator(BaseGuardrail):
    """Validates LLM output matches expected JSON schema."""

    SCHEMAS = {
        "extraction": {
            "type": "object",
            "required": ["tasks", "meeting_summary", "key_topics"],
            "properties": {
                "tasks": {"type": "array"},
                "meeting_summary": {"type": "string"},
                "key_topics": {"type": "array", "items": {"type": "string"}},
            },
        },
        "verification": {
            "type": "object",
            "required": ["faithfulness_score", "hallucination_score", "completeness_score", "verdict", "reasoning"],
            "properties": {
                "faithfulness_score": {"type": "number", "minimum": 0, "maximum": 1},
                "hallucination_score": {"type": "number", "minimum": 0, "maximum": 1},
                "completeness_score": {"type": "number", "minimum": 0, "maximum": 1},
                "verdict": {"type": "string", "enum": ["PASS", "FAIL", "NEEDS_REVIEW"]},
                "reasoning": {"type": "string"},
            },
        },
        "entity_resolution": {
            "type": "object",
            "required": ["assignee_id", "assignee_name", "assignee_email", "confidence", "method"],
            "properties": {
                "assignee_id": {"type": ["string", "null"]},
                "assignee_name": {"type": ["string", "null"]},
                "assignee_email": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "method": {"type": "string"},
            },
        },
        "conflict_resolution": {
            "type": "object",
            "required": ["resolved_tasks", "conflicts_resolved", "reasoning"],
            "properties": {
                "resolved_tasks": {"type": "array"},
                "conflicts_resolved": {"type": "integer"},
                "reasoning": {"type": "string"},
            },
        },
    }

    def __init__(self, enabled: bool = True, schema_name: str = "extraction"):
        super().__init__("format_validator", GuardrailLayer.OUTPUT, enabled)
        self.schema_name = schema_name
        self.schema = self.SCHEMAS.get(schema_name, {})

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Guardrail disabled")

        # Try to parse JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Output is not valid JSON for tenant {context.tenant_id}: {e}")
            return self._create_result(
                action=GuardrailAction.RETRY,
                severity=GuardrailSeverity.WARNING,
                message=f"Invalid JSON format: {str(e)}",
                metadata={"error": str(e), "schema": self.schema_name},
                confidence=1.0,
            )

        # Validate against schema (simplified - use jsonschema in production)
        errors = self._validate_schema(parsed, self.schema)
        if errors:
            logger.warning(f"Schema validation failed for tenant {context.tenant_id}: {errors}")
            return self._create_result(
                action=GuardrailAction.RETRY,
                severity=GuardrailSeverity.WARNING,
                message=f"Schema validation failed: {errors}",
                metadata={"errors": errors, "schema": self.schema_name},
                confidence=1.0,
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Format valid",
            metadata={"schema": self.schema_name},
        )

    def _validate_schema(self, data: dict, schema: dict, path: str = "") -> List[str]:
        """Simple schema validation."""
        errors = []

        if schema.get("type") == "object":
            if not isinstance(data, dict):
                return [f"{path}: expected object, got {type(data).__name__}"]

            required = schema.get("required", [])
            for field in required:
                if field not in data:
                    errors.append(f"{path}.{field}: required field missing")

            properties = schema.get("properties", {})
            for field, field_schema in properties.items():
                if field in data:
                    field_errors = self._validate_schema(data[field], field_schema, f"{path}.{field}")
                    errors.extend(field_errors)

        elif schema.get("type") == "array":
            if not isinstance(data, list):
                return [f"{path}: expected array, got {type(data).__name__}"]
            items_schema = schema.get("items", {})
            for i, item in enumerate(data):
                field_errors = self._validate_schema(item, items_schema, f"{path}[{i}]")
                errors.extend(field_errors)

        elif schema.get("type") == "string":
            if not isinstance(data, str):
                errors.append(f"{path}: expected string, got {type(data).__name__}")

        elif schema.get("type") == "number":
            if not isinstance(data, (int, float)):
                errors.append(f"{path}: expected number, got {type(data).__name__}")
            else:
                if "minimum" in schema and data < schema["minimum"]:
                    errors.append(f"{path}: value {data} below minimum {schema['minimum']}")
                if "maximum" in schema and data > schema["maximum"]:
                    errors.append(f"{path}: value {data} above maximum {schema['maximum']}")

        elif schema.get("type") == "boolean":
            if not isinstance(data, bool):
                errors.append(f"{path}: expected boolean, got {type(data).__name__}")

        return errors


# ─── Hallucination Detector ───

class HallucinationDetector(BaseGuardrail):
    """Detects hallucinations by checking grounding against transcript."""

    def __init__(
        self,
        enabled: bool = True,
        faithfulness_threshold: float = 0.7,
        hallucination_threshold: float = None,
    ):
        super().__init__("hallucination_detector", GuardrailLayer.OUTPUT, enabled)
        self.faithfulness_threshold = faithfulness_threshold
        # Keep both thresholds on the same scale by default, otherwise a
        # faithfulness score that passes the 0.7 bar can still trip the
        # hallucination check (1 - 0.7 = 0.3).
        self.hallucination_threshold = (
            hallucination_threshold
            if hallucination_threshold is not None
            else round(1.0 - faithfulness_threshold, 4)
        )

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Guardrail disabled")

        if not context.transcript_context:
            return self._create_result(
                GuardrailAction.FLAG,
                GuardrailSeverity.WARNING,
                "No transcript context for grounding check",
                metadata={"has_transcript": False},
            )

        # Parse output to extract claims
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return self._create_result(
                GuardrailAction.FLAG,
                GuardrailSeverity.WARNING,
                "Cannot check hallucination on non-JSON output",
            )

        # Extract text content from tasks
        tasks = parsed.get("tasks", [])
        if not tasks:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No tasks to verify")

        # Calculate faithfulness score
        faithfulness_score = await self._calculate_faithfulness(tasks, context.transcript_context)

        # Calculate hallucination score (inverse of faithfulness)
        hallucination_score = 1.0 - faithfulness_score

        metadata = {
            "faithfulness_score": faithfulness_score,
            "hallucination_score": hallucination_score,
            "threshold_faithfulness": self.faithfulness_threshold,
            "threshold_hallucination": self.hallucination_threshold,
            "num_tasks": len(tasks),
        }

        if hallucination_score > self.hallucination_threshold:
            logger.warning(f"High hallucination score ({hallucination_score:.2f}) for tenant {context.tenant_id}")
            return self._create_result(
                action=GuardrailAction.ROUTE_TO_HUMAN,
                severity=GuardrailSeverity.WARNING,
                message=f"Potential hallucination detected (score: {hallucination_score:.2f})",
                metadata=metadata,
                confidence=hallucination_score,
            )

        if faithfulness_score < self.faithfulness_threshold:
            logger.warning(f"Low faithfulness score ({faithfulness_score:.2f}) for tenant {context.tenant_id}")
            return self._create_result(
                action=GuardrailAction.ROUTE_TO_HUMAN,
                severity=GuardrailSeverity.WARNING,
                message=f"Low faithfulness to source (score: {faithfulness_score:.2f})",
                metadata=metadata,
                confidence=1.0 - faithfulness_score,
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Grounding check passed",
            metadata=metadata,
        )

    async def _calculate_faithfulness(self, tasks: List[dict], transcript: str) -> float:
        """
        Calculate faithfulness score.
        In production, use a dedicated faithfulness model or LLM-as-judge.
        Here: simple keyword overlap heuristic.
        """
        if not tasks:
            return 1.0

        transcript_words = set(transcript.lower().split())
        total_score = 0.0

        for task in tasks:
            # Combine task fields
            task_text = " ".join([
                task.get("title", ""),
                task.get("description", ""),
                task.get("source_quote", ""),
            ]).lower()

            task_words = set(task_text.split())
            if not task_words:
                continue

            # Calculate overlap
            overlap = task_words & transcript_words
            score = len(overlap) / len(task_words) if task_words else 1.0
            total_score += score

        return total_score / len(tasks) if tasks else 1.0


# ─── Confidence Threshold Guard ───

class ConfidenceThresholdGuard(BaseGuardrail):
    """Routes extractions based on confidence score."""

    THRESHOLDS = {
        "auto_approve": 0.90,
        "review_recommended": 0.70,
        "review_required": 0.50,
        "reject": 0.0,
    }

    def __init__(self, enabled: bool = True):
        super().__init__("confidence_threshold", GuardrailLayer.OUTPUT, enabled)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Guardrail disabled")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Non-JSON output")

        tasks = parsed.get("tasks", [])
        if not tasks:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No tasks")

        # Check each task's confidence
        actions = []
        for task in tasks:
            confidence = task.get("confidence", 0.0)
            if confidence >= self.THRESHOLDS["auto_approve"]:
                actions.append("auto_approve")
            elif confidence >= self.THRESHOLDS["review_recommended"]:
                actions.append("review_recommended")
            elif confidence >= self.THRESHOLDS["review_required"]:
                actions.append("review_required")
            else:
                actions.append("reject")

        # Determine overall action (worst case)
        if "reject" in actions:
            overall_action = GuardrailAction.ROUTE_TO_HUMAN
            severity = GuardrailSeverity.WARNING
            message = "Tasks below minimum confidence threshold"
        elif "review_required" in actions:
            overall_action = GuardrailAction.ROUTE_TO_HUMAN
            severity = GuardrailSeverity.WARNING
            message = "Tasks require human review"
        elif "review_recommended" in actions:
            overall_action = GuardrailAction.FLAG
            severity = GuardrailSeverity.INFO
            message = "Review recommended for some tasks"
        else:
            overall_action = GuardrailAction.ALLOW
            severity = GuardrailSeverity.INFO
            message = "All tasks auto-approved"

        return self._create_result(
            action=overall_action,
            severity=severity,
            message=message,
            metadata={
                "thresholds": self.THRESHOLDS,
                "task_confidences": [t.get("confidence", 0) for t in tasks],
                "actions": actions,
            },
        )


# ─── Contradiction Detector ───

class ContradictionDetector(BaseGuardrail):
    """Detects contradictions with prior extractions from same meeting."""

    def __init__(self, enabled: bool = True):
        super().__init__("contradiction_detector", GuardrailLayer.OUTPUT, enabled)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Guardrail disabled")

        if not context.prior_extractions:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No prior extractions")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Non-JSON output")

        new_tasks = parsed.get("tasks", [])
        if not new_tasks:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No new tasks")

        contradictions = []

        for new_task in new_tasks:
            new_title = new_task.get("title", "").lower()
            new_desc = new_task.get("description", "").lower()

            for prior in context.prior_extractions:
                prior_title = prior.get("title", "").lower()
                prior_desc = prior.get("description", "").lower()

                # Check for direct contradictions
                if self._is_contradiction(new_title, new_desc, prior_title, prior_desc):
                    contradictions.append({
                        "new_task": new_task.get("title"),
                        "prior_task": prior.get("title"),
                        "type": "direct_contradiction",
                    })
                    continue

                # Check for conflicting attributes on the same task
                attr_conflicts = self._attribute_conflicts(new_task, prior)
                contradictions.extend(attr_conflicts)

        if contradictions:
            logger.warning(f"Contradictions detected for tenant {context.tenant_id}: {len(contradictions)}")
            return self._create_result(
                action=GuardrailAction.ROUTE_TO_HUMAN,
                severity=GuardrailSeverity.WARNING,
                message=f"Contradictions detected with prior extractions: {len(contradictions)}",
                metadata={"contradictions": contradictions},
                confidence=0.8,
            )

        return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No contradictions")

    def _is_contradiction(self, new_title: str, new_desc: str, prior_title: str, prior_desc: str) -> bool:
        """Simple contradiction detection - in production use LLM or NLI model."""
        # Check for negation patterns
        negation_pairs = [
            ("will", "will not"),
            ("can", "cannot"),
            ("is", "is not"),
            ("approved", "rejected"),
            ("yes", "no"),
            ("true", "false"),
            ("complete", "incomplete"),
            ("done", "not done"),
        ]

        for pos, neg in negation_pairs:
            if pos in new_title and neg in prior_title:
                return True
            if neg in new_title and pos in prior_title:
                return True
            if pos in new_desc and neg in prior_desc:
                return True
            if neg in new_desc and pos in prior_desc:
                return True

        return False

    def _attribute_conflicts(self, new_task: dict, prior_task: dict) -> List[dict]:
        """Detect conflicting attribute values (e.g., deadline) for the same task."""
        conflicts = []

        new_title = (new_task.get("title") or "").strip().lower()
        prior_title = (prior_task.get("title") or "").strip().lower()
        if not new_title or not prior_title:
            return conflicts

        # Only compare when both extractions refer to the same task
        same_task = (
            new_title == prior_title
            or new_title in prior_title
            or prior_title in new_title
        )
        if not same_task:
            return conflicts

        for field in ("deadline_hint", "assignee_hint"):
            new_val = str(new_task.get(field) or "").strip().lower()
            prior_val = str(prior_task.get(field) or "").strip().lower()
            if new_val and prior_val and new_val != prior_val:
                conflicts.append({
                    "new_task": new_task.get("title"),
                    "prior_task": prior_task.get("title"),
                    "type": f"{field}_conflict",
                    "new_value": new_val,
                    "prior_value": prior_val,
                })

        return conflicts


# ─── Content Policy Guard ───

class ContentPolicyGuard(BaseGuardrail):
    """Checks output for harmful/biased content."""

    HARMFUL_PATTERNS = [
        # Hate speech indicators
        (r"\b(hate|despise|loathe)\s+(all|every)\s+\w+", "hate_speech"),
        # Violence
        (r"\b(kill|murder|assassinate|eliminate)\s+\w+", "violence"),
        # Self-harm
        (r"\b(suicide|kill myself|end my life)\b", "self_harm"),
        # PII requests
        (r"\b(ssn|social security|credit card|password)\s*(is|=|:)\s*\w+", "pii_request"),
        # Illegal acts
        (r"\b(steal|fraud|hack|breach|illegal)\b", "illegal_acts"),
    ]

    BIAS_PATTERNS = [
        r"\b(women|men|girls|boys)\s+(are|can't|cannot|always|never)\s+\w+",
        r"\b(asians|blacks|whites|hispanics|latinos)\s+(are|can't|cannot|always|never)",
        r"\b(disabled|handicapped)\s+people\s+(are|can't|cannot)",
    ]

    def __init__(self, enabled: bool = True):
        super().__init__("content_policy", GuardrailLayer.OUTPUT, enabled)
        self.harmful_compiled = [(re.compile(p, re.IGNORECASE), cat) for p, cat in self.HARMFUL_PATTERNS]
        self.bias_compiled = [re.compile(p, re.IGNORECASE) for p in self.BIAS_PATTERNS]

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Guardrail disabled")

        violations = []

        # Check harmful content
        for pattern, category in self.harmful_compiled:
            if pattern.search(content):
                violations.append({"type": category, "pattern": pattern.pattern})

        # Check bias
        for pattern in self.bias_compiled:
            if pattern.search(content):
                violations.append({"type": "bias", "pattern": pattern.pattern})

        if violations:
            logger.warning(f"Content policy violations for tenant {context.tenant_id}: {violations}")
            return self._create_result(
                action=GuardrailAction.BLOCK,
                severity=GuardrailSeverity.CRITICAL,
                message=f"Content policy violation: {len(violations)} issues",
                metadata={"violations": violations},
                confidence=0.85,
            )

        return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Content policy OK")


# ─── Output Guardrails Runner ───

class OutputGuardrailsRunner:
    """Runs all output guardrails in sequence."""

    def __init__(
        self,
        schema_name: str = "extraction",
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.guardrails = [
            FormatValidator(enabled=enabled, schema_name=schema_name),
            OutputPIIScanner(enabled=enabled),
            HallucinationDetector(enabled=enabled),
            ConfidenceThresholdGuard(enabled=enabled),
            ContradictionDetector(enabled=enabled),
            ContentPolicyGuard(enabled=enabled),
        ]

    async def run(self, content: str, context: GuardrailContext) -> List[GuardrailResult]:
        """Run all output guardrails."""
        if not self.enabled:
            return []

        results = []
        modified_content = content

        for guardrail in self.guardrails:
            result = await guardrail.check(modified_content, context)
            results.append(result)

            # If content was modified (e.g., PII redacted), use modified version
            if result.modified_content:
                modified_content = result.modified_content

            # Stop on BLOCK
            if result.action == GuardrailAction.BLOCK:
                break

            # On RETRY, could re-run with corrected format
            if result.action == GuardrailAction.RETRY:
                # In practice, would trigger a retry loop
                pass

        return results

    def get_final_action(self, results: List[GuardrailResult]) -> GuardrailAction:
        """Determine final action from all results."""
        # Priority: BLOCK > ROUTE_TO_HUMAN > RETRY > FLAG > ALLOW
        priority = {
            GuardrailAction.BLOCK: 5,
            GuardrailAction.ROUTE_TO_HUMAN: 4,
            GuardrailAction.RETRY: 3,
            GuardrailAction.FLAG: 2,
            GuardrailAction.ALLOW: 1,
        }

        max_priority = max(priority.get(r.action, 0) for r in results)
        for action, p in priority.items():
            if p == max_priority:
                return action

        return GuardrailAction.ALLOW