from pydantic import BaseModel, Field
from typing import Literal, List, Optional
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


class VerificationResult(BaseModel):
    faithfulness_score: float = Field(ge=0, le=1)
    hallucination_score: float = Field(ge=0, le=1)
    completeness_score: float = Field(ge=0, le=1)
    verdict: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    reasoning: str


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