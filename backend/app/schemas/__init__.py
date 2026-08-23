from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Literal, Any
from datetime import datetime
from uuid import UUID
from enum import Enum
import uuid


# ─── Base Models ───
from pydantic.alias_generators import to_camel


def to_prisma_data(model: BaseModel) -> dict:
    """Convert a Pydantic model's explicitly-set fields into Prisma-compatible data.

    Prisma's Python client expects camelCase field names plus JSON-mode values
    (UUID -> str, datetime -> ISO string). Feeding raw snake_case ``model_dump``
    output raises runtime errors on every update path, so all update endpoints
    should route through this helper.
    """
    return {
        to_camel(k): v
        for k, v in model.model_dump(mode="json", exclude_unset=True).items()
        if v is not None
    }

class BaseModelConfig(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )

class TimestampMixin(BaseModelConfig):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UUIDMixin(BaseModelConfig):
    id: UUID = Field(default_factory=uuid.uuid4)


# ─── Enums ───

class MeetingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    TRANSCRIBED = "TRANSCRIBED"
    EXTRACTED = "EXTRACTED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class TaskStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    ASSIGNED = "ASSIGNED"
    SYNCED = "SYNCED"
    SYNC_FAILED = "SYNC_FAILED"
    CONFLICT = "CONFLICT"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"


class TaskType(str, Enum):
    ACTION_ITEM = "ACTION_ITEM"
    DECISION = "DECISION"
    FOLLOW_UP = "FOLLOW_UP"
    BLOCKER = "BLOCKER"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    SYNC_FAILED = "SYNC_FAILED"
    CONFLICT = "CONFLICT"


class IntegrationProvider(str, Enum):
    JIRA = "jira"
    ASANA = "asana"
    LINEAR = "linear"
    SLACK = "slack"
    TEAMS = "teams"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ─── Core Domain Models ───

class TenantBase(BaseModel):
    name: str
    slug: str
    plan: str = "starter"
    status: str = "active"


class TenantCreate(TenantBase):
    pass


class Tenant(TenantBase, UUIDMixin, TimestampMixin):
    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    role: str = "member"
    clerk_user_id: Optional[str] = None


class UserCreate(UserBase):
    tenant_id: UUID


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None


class User(UserBase, UUIDMixin, TimestampMixin):
    tenant_id: UUID
    model_config = ConfigDict(from_attributes=True)


class UserResponse(User):
    pass


class MeetingBase(BaseModelConfig):
    title: str
    description: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: Optional[int] = None
    audio_url: Optional[str] = None
    recording_source: str = "upload"
    calendar_event_id: Optional[str] = None


class MeetingCreate(MeetingBase):
    tenant_id: UUID


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    audio_url: Optional[str] = None
    status: Optional[MeetingStatus] = None


class Meeting(MeetingBase, UUIDMixin, TimestampMixin):
    tenant_id: UUID
    status: MeetingStatus = MeetingStatus.UPLOADED
    model_config = ConfigDict(from_attributes=True)


class AttendeeBase(BaseModel):
    email: str
    display_name: str
    speaker_label: Optional[str] = None
    response_status: str = "accepted"


class AttendeeCreate(AttendeeBase):
    meeting_id: UUID
    user_id: Optional[UUID] = None


class Attendee(AttendeeBase, UUIDMixin, TimestampMixin):
    meeting_id: UUID
    user_id: Optional[UUID] = None
    model_config = ConfigDict(from_attributes=True)


class TranscriptBase(BaseModel):
    full_text: str
    language: str = "en"
    word_count: int = 0
    duration_ms: int = 0
    redaction_applied: bool = False


class TranscriptCreate(TranscriptBase):
    meeting_id: UUID


class Transcript(TranscriptBase, UUIDMixin, TimestampMixin):
    meeting_id: UUID
    model_config = ConfigDict(from_attributes=True)


class UtteranceBase(BaseModel):
    speaker_label: str
    text: str
    start_time_ms: int
    end_time_ms: int
    confidence: Optional[float] = None
    word_start_idx: Optional[int] = None
    word_end_idx: Optional[int] = None
    has_redactions: bool = False
    redaction_map: Optional[dict] = None


class UtteranceCreate(UtteranceBase):
    transcript_id: UUID


class Utterance(UtteranceBase, UUIDMixin):
    transcript_id: UUID
    model_config = ConfigDict(from_attributes=True)


class TranscriptSpan(BaseModel):
    start_word_idx: int
    end_word_idx: int
    start_time_ms: int
    end_time_ms: int
    speaker_label: str
    text: str
    confidence: float


class TranscriptChunk(BaseModel):
    index: int
    text: str
    word_start: int
    word_end: int
    speakers: List[str]


# ─── Task Models ───

class TaskBase(BaseModel):
    title: str = Field(..., max_length=500)
    description: str
    task_type: TaskType
    priority: Optional[Priority] = None
    
    # Assignee
    assignee_hint: Optional[str] = None
    assignee_id: Optional[UUID] = None
    assignee_resolved_by: Optional[str] = None
    
    # Deadline
    deadline_hint: Optional[str] = None
    deadline_date: Optional[datetime] = None
    deadline_resolved_by: Optional[str] = None
    
    # Transcript provenance
    transcript_word_start: int
    transcript_word_end: int
    source_quote: str
    
    # Verification
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verification_reasoning: Optional[str] = None
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    
    # Integration
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    integration_id: Optional[UUID] = None
    last_synced_at: Optional[datetime] = None
    sync_status: Optional[SyncStatus] = None
    
    created_by: str = "ai_agent"


class TaskCreate(TaskBase):
    tenant_id: UUID
    meeting_id: UUID


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[TaskType] = None
    status: Optional[TaskStatus] = None
    priority: Optional[Priority] = None
    assignee_hint: Optional[str] = None
    assignee_id: Optional[UUID] = None
    assignee_resolved_by: Optional[str] = None
    deadline_hint: Optional[str] = None
    deadline_date: Optional[datetime] = None
    deadline_resolved_by: Optional[str] = None
    verification_status: Optional[VerificationStatus] = None
    verification_reasoning: Optional[str] = None
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    integration_id: Optional[UUID] = None
    sync_status: Optional[SyncStatus] = None


class Task(TaskBase, UUIDMixin, TimestampMixin):
    tenant_id: UUID
    meeting_id: UUID
    status: TaskStatus = TaskStatus.EXTRACTED
    model_config = ConfigDict(from_attributes=True)


class TaskAuditLogBase(BaseModel):
    previous_status: Optional[TaskStatus] = None
    new_status: TaskStatus
    changed_by: str
    reason: Optional[str] = None
    metadata: Optional[dict] = None


class TaskAuditLogCreate(TaskAuditLogBase):
    task_id: UUID


class TaskAuditLog(TaskAuditLogBase, UUIDMixin):
    task_id: UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ─── Integration Models ───

class IntegrationBase(BaseModel):
    provider: IntegrationProvider
    display_name: str
    config: dict = {}
    webhook_secret: Optional[str] = None


class IntegrationCreate(IntegrationBase):
    tenant_id: UUID


class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    config: Optional[dict] = None
    status: Optional[str] = None
    webhook_secret: Optional[str] = None


class Integration(IntegrationBase, UUIDMixin, TimestampMixin):
    tenant_id: UUID
    status: str = "ACTIVE"
    model_config = ConfigDict(from_attributes=True)


class WebhookEvent(BaseModel):
    event: str
    payload: dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# ─── AI Audit Models ───

class AiAuditLogBase(BaseModel):
    decision_type: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    raw_input_hash: Optional[str] = None
    raw_output: Optional[str] = None
    structured_output: Optional[dict] = None
    verification_result: Optional[dict] = None
    latency_ms: Optional[int] = None


class AiAuditLogCreate(AiAuditLogBase):
    tenant_id: UUID
    task_id: Optional[UUID] = None
    meeting_id: Optional[UUID] = None


class AiAuditLog(AiAuditLogBase, UUIDMixin):
    tenant_id: UUID
    task_id: Optional[UUID] = None
    meeting_id: Optional[UUID] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ─── Meeting Flag Models ───

class MeetingFlagBase(BaseModel):
    flag_type: str
    message: str
    resolved: bool = False
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None


class MeetingFlagCreate(MeetingFlagBase):
    meeting_id: UUID


class MeetingFlag(MeetingFlagBase, UUIDMixin):
    meeting_id: UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ─── Response Models ───

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    services: dict