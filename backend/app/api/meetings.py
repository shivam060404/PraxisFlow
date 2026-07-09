from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import uuid

from app.db.prisma import get_db, prisma_context
from app.schemas import (
    Meeting, MeetingCreate, MeetingUpdate, MeetingStatus,
    Attendee, AttendeeCreate,
    PaginatedResponse, ErrorResponse
)
from app.core.config import settings
from app.services.storage import StorageService
from app.workers.tasks import process_meeting

router = APIRouter(prefix="/meetings", tags=["Meetings"])


@router.post("", response_model=Meeting, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    meeting_data: MeetingCreate,
    db=Depends(get_db),
):
    """Create a new meeting record."""
    meeting = await db.meeting.create(
        data={
            "tenantId": str(meeting_data.tenant_id),
            "title": meeting_data.title,
            "description": meeting_data.description,
            "scheduledAt": meeting_data.scheduled_at,
            "durationMinutes": meeting_data.duration_minutes,
            "audioUrl": meeting_data.audio_url,
            "recordingSource": meeting_data.recording_source,
            "calendarEventId": meeting_data.calendar_event_id,
        }
    )
    return meeting


@router.post("/upload", response_model=Meeting, status_code=status.HTTP_201_CREATED)
async def upload_meeting(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    scheduled_at: str = Form(...),
    duration_minutes: Optional[int] = Form(None),
    tenant_id: str = Form(...),
    db=Depends(get_db),
):
    """Upload a meeting audio/video file."""
    # Validate file type
    if file.content_type not in settings.ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}",
        )
    
    # Validate file size
    file_size = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    while chunk := await file.read(chunk_size):
        file_size += len(chunk)
        if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit",
            )
    
    # Reset file pointer
    await file.seek(0)
    
    # Upload to MinIO
    storage = StorageService()
    meeting_id = uuid.uuid4()
    object_name = f"{tenant_id}/{meeting_id}/{file.filename}"
    
    audio_url = await storage.upload_file(
        bucket=settings.MINIO_BUCKET_AUDIO,
        object_name=object_name,
        file=file.file,
        content_type=file.content_type,
    )
    
    # Create meeting record
    meeting = await db.meeting.create(
        data={
            "id": str(meeting_id),
            "tenantId": tenant_id,
            "title": title,
            "description": description,
            "scheduledAt": datetime.fromisoformat(scheduled_at.replace('Z', '+00:00')),
            "durationMinutes": duration_minutes,
            "audioUrl": audio_url,
            "recordingSource": "upload",
            "status": "UPLOADED",
        }
    )
    
    # Queue processing job
    process_meeting.delay(str(meeting_id))
    
    return meeting


@router.get("", response_model=PaginatedResponse)
async def list_meetings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[MeetingStatus] = None,
    db=Depends(get_db),
):
    """List meetings with pagination and filtering."""
    where = {}
    if status:
        where["status"] = status
    
    total = await db.meeting.count(where=where)
    meetings = await db.meeting.find_many(
        where=where,
        skip=(page - 1) * page_size,
        take=page_size,
        order={"scheduledAt": "desc"},
        include={"transcript": True, "attendees": True, "_count": {"select": {"tasks": True}}},
    )
    
    return PaginatedResponse(
        items=meetings,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{meeting_id}", response_model=Meeting)
async def get_meeting(
    meeting_id: UUID,
    db=Depends(get_db),
):
    """Get a single meeting by ID."""
    meeting = await db.meeting.find_unique(
        where={"id": str(meeting_id)},
        include={"transcript": True, "attendees": True, "tasks": True},
    )
    
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    return meeting


@router.patch("/{meeting_id}", response_model=Meeting)
async def update_meeting(
    meeting_id: UUID,
    meeting_data: MeetingUpdate,
    db=Depends(get_db),
):
    """Update a meeting."""
    meeting = await db.meeting.find_unique(where={"id": str(meeting_id)})
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    update_data = meeting_data.model_dump(exclude_unset=True)
    if "scheduled_at" in update_data:
        update_data["scheduledAt"] = update_data.pop("scheduled_at")
    
    updated = await db.meeting.update(
        where={"id": str(meeting_id)},
        data=update_data,
    )
    
    return updated


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: UUID,
    db=Depends(get_db),
):
    """Delete a meeting."""
    meeting = await db.meeting.find_unique(where={"id=str(meeting_id))
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    # Delete from storage
    storage = StorageService()
    if meeting.audioUrl:
        await storage.delete_file(meeting.audioUrl)
    
    await db.meeting.delete(where={"id": str(meeting_id)})


@router.post("/{meeting_id}/attendees", response_model=Attendee, status_code=status.HTTP_201_CREATED)
async def add_attendee(
    meeting_id: UUID,
    attendee_data: AttendeeCreate,
    db=Depends(get_db),
):
    """Add an attendee to a meeting."""
    meeting = await db.meeting.find_unique(where={"id": str(meeting_id)})
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    attendee = await db.attendee.create(
        data={
            "meetingId": str(meeting_id),
            "userId": str(attendee_data.user_id) if attendee_data.user_id else None,
            "email": attendee_data.email,
            "displayName": attendee_data.display_name,
            "speakerLabel": attendee_data.speaker_label,
            "responseStatus": attendee_data.response_status,
        }
    )
    
    return attendee


@router.get("/{meeting_id}/attendees", response_model=List[Attendee])
async def list_attendees(
    meeting_id: UUID,
    db=Depends(get_db),
):
    """List attendees for a meeting."""
    meeting = await db.meeting.find_unique(where={"id": str(meeting_id)})
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    attendees = await db.attendee.find_many(
        where={"meetingId": str(meeting_id)},
    )
    
    return attendees


@router.post("/{meeting_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_meeting(
    meeting_id: UUID,
    db=Depends(get_db),
):
    """Reprocess a meeting (re-run ASR and extraction)."""
    meeting = await db.meeting.find_unique(where={"id": str(meeting_id)})
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    
    # Reset status and queue processing
    await db.meeting.update(
        where={"id": str(meeting_id)},
        data={"status": "UPLOADED"},
    )
    
    process_meeting.delay(str(meeting_id))
    
    return {"message": "Meeting queued for reprocessing", "meeting_id": str(meeting_id)}