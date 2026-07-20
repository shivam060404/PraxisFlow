"""
Input Guardrails for PraxisFlow
Pre-LLM validation: injection detection, PII scanning, topic boundaries, jailbreak detection
"""

import re
import logging
from typing import Dict, List, Optional, Any

from app.guardrails.base import BaseGuardrail, GuardrailAction, GuardrailLayer, GuardrailSeverity, GuardrailResult, GuardrailContext
from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── Prompt Injection Detector ───

class PromptInjectionDetector(BaseGuardrail):
    """
    Detects prompt injection attempts using pattern matching.
    In production, augment with ML classifier (Lakera Guard, custom model).
    """

    INJECTION_PATTERNS = [
        # Direct instruction override
        r"ignore\s+(previous|above|all)\s+(instructions|prompts|rules)",
        r"disregard\s+(previous|above|all)\s+(instructions|prompts|rules)",
        r"forget\s+(everything|all)\s+(you|above)",
        r"you\s+are\s+now\s+(a|an)\s+\w+",
        r"act\s+as\s+(a|an)\s+\w+",
        r"pretend\s+to\s+be",
        r"roleplay\s+as",

        # System prompt manipulation
        r"system\s*:\s*you",
        r"assistant\s*:\s*you",
        r"###\s*instruction",
        r"```\s*system",
        r"<system>",
        r"\[INST\]",
        r"\[SYS\]",
        r"<\|im_start\|>\s*system",
        r"<\|system\|>",

        # Override/bypass
        r"override",
        r"bypass",
        r"jailbreak",
        r"dan\s+mode",
        r"developer\s+mode",
        r"ignore\s+guardrails",
        r"disable\s+safety",
        r"no\s+(moral|ethical|safety)\s+(guidelines|constraints|rules)",
        r"you\s+(have\s+)?no\s+(restrictions|limits|boundaries)",
        r"free\s+(mode|version)",
        r"uncensored",
        r"unrestricted",
        r"unfiltered",
        r"simulate\s+(an\s+)?(unrestricted|unfiltered)",

        # Data exfiltration
        r"repeat\s+(the\s+)?(prompt|instructions|system\s+prompt)",
        r"show\s+me\s+(the\s+)?(prompt|instructions|system\s+prompt)",
        r"what\s+(is|was)\s+(the\s+)?(prompt|instruction)",

        # Encoding/obfuscation
        r"base64",
        r"rot13",
        r"encoded",
        r"\\x[0-9a-f]{2}",
        r"&#x[0-9a-f]+;",
    ]

    def __init__(
        self,
        enabled: bool = True,
        use_ml_classifier: bool = False,
    ):
        super().__init__("prompt_injection_detector", GuardrailLayer.INPUT, enabled)
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]
        self.use_ml_classifier = use_ml_classifier
        self._ml_classifier = None

    async def initialize_ml_classifier(self):
        """Initialize ML-based injection classifier if available."""
        if self.use_ml_classifier:
            try:
                # Example: self._ml_classifier = LakeraGuardClient(api_key=settings.LAKERA_API_KEY)
                logger.info("ML injection classifier initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize ML classifier: {e}")
                self.use_ml_classifier = False

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        matches = []
        for pattern in self.compiled_patterns:
            if pattern.search(content):
                matches.append(pattern.pattern)

        # ML classifier (if enabled)
        ml_score = 0.0
        if self.use_ml_classifier and self._ml_classifier:
            try:
                ml_score = await self._ml_classifier.score(content)
                if ml_score > 0.8:
                    matches.append(f"ml_classifier_score:{ml_score:.2f}")
            except Exception as e:
                logger.error(f"ML classifier error: {e}")

        if matches:
            logger.warning(
                f"Prompt injection detected for tenant {context.tenant_id}, "
                f"request {context.request_id}: {len(matches)} matches"
            )
            return self._create_result(
                action=GuardrailAction.BLOCK,
                severity=GuardrailSeverity.CRITICAL,
                message=f"Prompt injection detected: {len(matches)} pattern(s) matched",
                metadata={
                    "matched_patterns": matches[:10],
                    "content_length": len(content),
                    "ml_score": ml_score if ml_score else None,
                },
                confidence=0.9,
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "No injection detected",
            metadata={"patterns_checked": len(self.compiled_patterns)},
        )


# ─── PII Input Scanner ───

class InputPIIScanner(BaseGuardrail):
    """
    Scans input for PII using regex patterns.
    For production, integrate with Microsoft Presidio or AWS Comprehend.
    """

    PII_PATTERNS = {
        "email": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", True),
        "phone_us": (r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", True),
        "phone_intl": (r"\+\d{1,3}[-.\s]?\d{1,14}", True),
        "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", True),
        "credit_card": (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", True),
        "ipv4": (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", False),
        "ipv6": (r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b", False),
        "api_key_generic": (r"(sk|pk|api)[-_]?[a-zA-Z0-9]{32,}", True),
        "aws_access_key": (r"AKIA[0-9A-Z]{16}", True),
        "github_token": (r"gh[pousr]_[a-zA-Z0-9]{36,}", True),
        "gitlab_token": (r"glpat-[a-zA-Z0-9_-]{20,}", True),
        "slack_token": (r"xox[baprs]-[a-zA-Z0-9-]{10,}", True),
        "jwt": (r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*", True),
        "database_url": (r"(postgres|mysql|mongodb|redis)://[^:\s]+:[^@\s]+@[^/\s]+", True),
        "private_key": (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", True),
        "address_us": (r"\b\d+\s+[A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl)\b", False),
        "zip_us": (r"\b\d{5}(?:-\d{4})?\b", False),
        "date_of_birth": (r"\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}\b", True),
        "passport_us": (r"\b[A-Z]{1}\d{8}\b", True),
        "driver_license_ca": (r"\b[Dd]\d{7}\b", True),
    }

    def __init__(
        self,
        enabled: bool = True,
        action: GuardrailAction = GuardrailAction.REDACT,
        custom_patterns: Dict[str, tuple] = None,
    ):
        super().__init__("input_pii_scanner", GuardrailLayer.INPUT, enabled)
        self.action = action
        self.custom_patterns = custom_patterns or {}
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile all regex patterns."""
        self.compiled = {}
        all_patterns = {**self.PII_PATTERNS, **self.custom_patterns}
        for name, (pattern, is_sensitive) in all_patterns.items():
            self.compiled[name] = (re.compile(pattern), is_sensitive)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        detected = {}
        redacted_content = content

        for name, (pattern, is_sensitive) in self.compiled.items():
            matches = pattern.findall(content)
            if matches:
                detected[name] = {
                    "count": len(matches),
                    "sensitive": is_sensitive,
                    "examples": matches[:3] if is_sensitive else matches[:5],
                }

                if self.action == GuardrailAction.REDACT:
                    redacted_content = pattern.sub(f"[REDACTED_{name.upper()}]", redacted_content)

        if detected:
            logger.info(f"PII detected in input for tenant {context.tenant_id}: {list(detected.keys())}")

            severity = GuardrailSeverity.WARNING
            if any(d["sensitive"] for d in detected.values()):
                severity = GuardrailSeverity.CRITICAL

            return self._create_result(
                action=self.action,
                severity=severity,
                message=f"PII detected: {', '.join(detected.keys())}",
                metadata={
                    "pii_types": detected,
                    "redacted": self.action == GuardrailAction.REDACT,
                },
                modified_content=redacted_content if self.action == GuardrailAction.REDACT else None,
                confidence=0.95,
            )

        return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No PII detected")


# ─── Topic Boundary Guard ───

class TopicBoundaryGuard(BaseGuardrail):
    """Ensures input stays within meeting/transcript processing domain."""

    MEETING_KEYWORDS = {
        "meeting", "transcript", "recording", "audio", "video",
        "action item", "task", "decision", "follow up", "follow-up",
        "blocker", "agenda", "minutes", "discussion", "attendee",
        "participant", "speaker", "deadline", "assignee", "priority",
        "sprint", "standup", "retrospective", "planning", "review",
        "demo", "sync", "alignment", "check-in", "catch up",
        "summary", "extract", "analyze", "process", "identify",
        "actionable", "deliverable", "milestone", "commitment",
    }

    OFF_TOPIC_CATEGORIES = {
        "coding": [
            "write code", "programming", "coding", "debug", "function",
            "class", "algorithm", "api", "database", "sql", "query",
            "javascript", "python", "react", "node", "docker", "kubernetes",
            "git", "github", "pull request", "commit", "merge", "deploy",
        ],
        "creative_writing": [
            "write a story", "poem", "creative writing", "fiction",
            "novel", "short story", "screenplay", "script", "character",
            "plot", "dialogue", "scene", "chapter",
        ],
        "general_qa": [
            "what is", "how to", "explain", "define", "meaning of",
            "difference between", "compare", "why does", "when did",
        ],
        "personal_advice": [
            "medical advice", "legal advice", "financial advice",
            "investment", "crypto", "gambling", "relationship advice",
        ],
    }

    def __init__(self, enabled: bool = True, strict: bool = False):
        super().__init__("topic_boundary", GuardrailLayer.INPUT, enabled)
        self.strict = strict

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        content_lower = content.lower()

        # Check for meeting relevance
        meeting_score = sum(1 for kw in self.MEETING_KEYWORDS if kw in content_lower)

        # Check for off-topic indicators
        off_topic_scores = {}
        for category, keywords in self.OFF_TOPIC_CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                off_topic_scores[category] = score

        total_off_topic = sum(off_topic_scores.values())

        # Decision logic
        if self.strict:
            # Strict: must have meeting keywords and no off-topic
            if meeting_score == 0 or total_off_topic > 0:
                return self._create_result(
                    action=GuardrailAction.BLOCK,
                    severity=GuardrailSeverity.WARNING,
                    message="Input outside meeting processing domain",
                    metadata={
                        "meeting_score": meeting_score,
                        "off_topic_scores": off_topic_scores,
                    },
                    confidence=0.8,
                )
        else:
            # Lenient: warn if heavily off-topic
            if total_off_topic > meeting_score and total_off_topic > 2:
                return self._create_result(
                    action=GuardrailAction.FLAG,
                    severity=GuardrailSeverity.WARNING,
                    message="Input appears off-topic for meeting processing",
                    metadata={
                        "meeting_score": meeting_score,
                        "off_topic_scores": off_topic_scores,
                    },
                    confidence=0.7,
                )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Topic boundary OK",
            metadata={"meeting_score": meeting_score, "off_topic_scores": off_topic_scores},
        )


# ─── Jailbreak Detector ───

class JailbreakDetector(BaseGuardrail):
    """Detects known jailbreak patterns."""

    JAILBREAK_PATTERNS = [
        r"DAN|Do Anything Now",
        r"STAN|Strive To Avoid Norms",
        r"DUDE|Do You Ever Do Everything",
        r"Mongo Tom",
        r"Evil Confidant",
        r"AntiGPT",
        r"Waluigi",
        r"unrestricted",
        r"unfiltered",
        r"no\s+(moral|ethical|safety)\s+(guidelines|constraints|rules)",
        r"ignore\s+(all\s+)?(safety|moral|ethical)",
        r"you\s+(have\s+)?no\s+(restrictions|limits|boundaries)",
        r"free\s+(mode|version)",
        r"uncensored",
        r"simulate\s+(an\s+)?(unrestricted|unfiltered)",
    ]

    def __init__(self, enabled: bool = True):
        super().__init__("jailbreak_detector", GuardrailLayer.INPUT, enabled)
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.JAILBREAK_PATTERNS]

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        matches = []
        for pattern in self.compiled_patterns:
            if pattern.search(content):
                matches.append(pattern.pattern)

        if matches:
            logger.warning(f"Jailbreak attempt detected for tenant {context.tenant_id}: {matches}")
            return self._create_result(
                action=GuardrailAction.BLOCK,
                severity=GuardrailSeverity.CRITICAL,
                message="Jailbreak pattern detected",
                metadata={"matched_patterns": matches[:5]},
                confidence=0.85,
            )

        return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "No jailbreak detected")


# ─── Input Length Validator ───

class InputLengthValidator(BaseGuardrail):
    """Validates input length to prevent context overflow attacks."""

    def __init__(
        self,
        max_chars: int = 100000,
        max_tokens_estimate: int = 25000,
        enabled: bool = True,
    ):
        super().__init__("input_length_validator", GuardrailLayer.INPUT, enabled)
        self.max_chars = max_chars
        self.max_tokens_estimate = max_tokens_estimate

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        char_count = len(content)
        token_estimate = char_count / 4  # Rough estimate: ~4 chars per token

        if char_count > self.max_chars:
            return self._create_result(
                action=GuardrailAction.BLOCK,
                severity=GuardrailSeverity.WARNING,
                message=f"Input exceeds maximum character limit ({char_count} > {self.max_chars})",
                metadata={"char_count": char_count, "max_chars": self.max_chars},
                confidence=1.0,
            )

        if token_estimate > self.max_tokens_estimate:
            return self._create_result(
                action=GuardrailAction.BLOCK,
                severity=GuardrailSeverity.WARNING,
                message=f"Input exceeds estimated token limit ({token_estimate:.0f} > {self.max_tokens_estimate})",
                metadata={"token_estimate": token_estimate, "max_tokens": self.max_tokens_estimate},
                confidence=1.0,
            )

        return self._create_result(
            GuardrailAction.ALLOW,
            GuardrailSeverity.INFO,
            "Length OK",
            metadata={"char_count": char_count, "token_estimate": token_estimate},
        )


# ─── Tenant Isolation Guard ───

class TenantIsolationGuard(BaseGuardrail):
    """Ensures no cross-tenant data references in input."""

    def __init__(self, enabled: bool = True):
        super().__init__("tenant_isolation", GuardrailLayer.INPUT, enabled)
        self.uuid_pattern = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE)

    async def check(self, content: str, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Disabled")

        uuids = self.uuid_pattern.findall(content)

        if uuids:
            # Check if any UUID doesn't match current context
            suspicious = []
            for uuid in uuids:
                if (uuid != context.tenant_id and
                    uuid != context.meeting_id and
                    uuid != context.user_id and
                    uuid not in context.prior_extractions):
                    suspicious.append(uuid)

            if suspicious:
                logger.warning(f"Potential cross-tenant reference for tenant {context.tenant_id}: {suspicious}")
                return self._create_result(
                    action=GuardrailAction.FLAG,
                    severity=GuardrailSeverity.WARNING,
                    message="Potential cross-tenant reference detected",
                    metadata={"referenced_uuids": suspicious},
                    confidence=0.6,
                )

        return self._create_result(GuardrailAction.ALLOW, GuardrailSeverity.INFO, "Tenant isolation OK")


# ─── Input Guardrails Factory ───

def create_input_guardrails(config: Dict[str, Any] = None) -> List[BaseGuardrail]:
    """Create standard input guardrails pipeline."""
    config = config or {}

    return [
        PromptInjectionDetector(
            enabled=config.get("injection_detection", True),
            use_ml_classifier=config.get("use_ml_injection_classifier", False),
        ),
        InputPIIScanner(
            enabled=config.get("pii_scanning", True),
            action=GuardrailAction(config.get("pii_action", "redact")),
        ),
        TopicBoundaryGuard(
            enabled=config.get("topic_boundary", True),
            strict=config.get("strict_topic_boundary", False),
        ),
        JailbreakDetector(
            enabled=config.get("jailbreak_detection", True),
        ),
        InputLengthValidator(
            enabled=config.get("length_validation", True),
            max_chars=config.get("max_chars", 100000),
            max_tokens_estimate=config.get("max_tokens", 25000),
        ),
        TenantIsolationGuard(
            enabled=config.get("tenant_isolation", True),
        ),
    ]