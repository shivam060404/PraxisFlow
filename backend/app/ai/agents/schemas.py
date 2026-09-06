from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Dict, Any
from datetime import datetime
import uuid


class ExtractedTask(BaseModel):
    task_type: Literal["ACTION_ITEM", "DECISION", "FOLLOW_UP", "BLOCKER"] = Field(
        description="Classification of the extracted item"
    )
    title: str = Field(description="Concise task title, max 10 words")
    description: str = Field(description="Detailed description with context")
    assignee_hint: Optional[str] = Field(
        default=None,
        description="Name or role mentioned as assignee, e.g. 'Sarah from engineering'"
    )
    deadline_hint: Optional[str] = Field(
        default=None,
        description="Deadline mentioned, e.g. 'by Friday' or 'end of Q2'"
    )
    priority_hint: Optional[Literal["HIGH", "MEDIUM", "LOW"]] = Field(
        default=None,
        description="Explicit priority if stated"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence")
    transcript_word_start: int = Field(description="Start word index in transcript")
    transcript_word_end: int = Field(description="End word index in transcript")
    source_quote: str = Field(description="Verbatim quote from transcript")

    # Verification fields
    verification_status: Literal["UNVERIFIED", "VERIFIED", "NEEDS_REVIEW", "FAILED"] = "UNVERIFIED"
    verification_reasoning: Optional[str] = None
    faithfulness_score: Optional[float] = Field(default=None, ge=0, le=1)
    hallucination_score: Optional[float] = Field(default=None, ge=0, le=1)
    completeness_score: Optional[float] = Field(default=None, ge=0, le=1)

    # Assignee resolution fields (filled by entity_resolution_node)
    assignee_id: Optional[str] = None
    assignee_resolved_by: Optional[str] = None

    # HITL fields
    requires_human_review: bool = False
    human_review_reason: Optional[str] = None


class ExtractionResult(BaseModel):
    tasks: List[ExtractedTask] = Field(default_factory=list)
    meeting_summary: str = Field(description="2-3 sentence meeting summary")
    key_topics: List[str] = Field(description="Key topics discussed")


class TranscriptChunk(BaseModel):
    index: int
    text: str
    word_start: int
    word_end: int
    speakers: List[str]


class ExtractionState(BaseModel):
    meeting_id: str
    tenant_id: str
    user_id: str
    meeting_context: str
    transcript_chunks: List[TranscriptChunk]
    current_chunk_index: int = 0
    proposed_tasks: List[ExtractedTask] = Field(default_factory=list)
    verified_tasks: List[ExtractedTask] = Field(default_factory=list)
    deduplicated_tasks: List[ExtractedTask] = Field(default_factory=list)
    final_tasks: List[ExtractedTask] = Field(default_factory=list)
    meeting_summary: str = ""
    key_topics: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    # HITL / Interrupt state
    interrupted: bool = False
    interrupt_reason: Optional[str] = None
    interrupt_node: Optional[str] = None
    interrupt_payload: Optional[Dict[str, Any]] = None
    human_feedback: Optional[Dict[str, Any]] = None

    # Retry / Repair state
    retry_count: Dict[str, int] = Field(default_factory=dict)
    last_error: Optional[str] = None

    # Observability
    trace_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None


class VerificationResult(BaseModel):
    faithfulness_score: float = Field(ge=0, le=1)
    hallucination_score: float = Field(ge=0, le=1)
    completeness_score: float = Field(ge=0, le=1)
    verdict: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    reasoning: str
    supporting_quote: Optional[str] = Field(default=None, description="Exact transcript quote supporting the verdict")


class GroundedVerificationInput(BaseModel):
    """Input for grounded verification with transcript context."""
    task: ExtractedTask
    transcript_segment: str
    full_transcript_context: Optional[str] = None


class EntityResolutionResult(BaseModel):
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_email: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    method: str = "unknown"
    candidates: List[dict] = Field(default_factory=list)


class TaskWithResolution(BaseModel):
    task: ExtractedTask
    assignee_resolution: Optional[EntityResolutionResult] = None
    deadline_resolution: Optional[datetime] = None


class JSONRepairAttempt(BaseModel):
    """Tracks a JSON repair attempt."""
    original_output: str
    error: str
    repaired_output: Optional[str] = None
    success: bool = False
    attempt_number: int = 1


class HITLPayload(BaseModel):
    """Payload for human-in-the-loop interrupt."""
    meeting_id: str
    tenant_id: str
    task_id: Optional[str] = None
    interrupt_reason: str
    task_data: Dict[str, Any]
    confidence_score: float
    suggested_action: Literal["APPROVE", "REJECT", "MODIFY"]
    transcript_evidence: str
    expires_at: Optional[datetime] = None