from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.db.prisma import get_db
from app.schemas import (
    Task, TaskCreate, TaskUpdate, TaskStatus, TaskType,
    Priority, VerificationStatus, SyncStatus,
    TaskAuditLog, TaskAuditLogCreate,
    PaginatedResponse
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_data: TaskCreate,
    db=Depends(get_db),
):
    """Create a new task (usually called by extraction pipeline)."""
    task = await db.task.create(
        data={
            "tenantId": str(task_data.tenant_id),
            "meetingId": str(task_data.meeting_id),
            "title": task_data.title,
            "description": task_data.description,
            "taskType": task_data.task_type,
            "priority": task_data.priority,
            "assigneeHint": task_data.assignee_hint,
            "assigneeId": str(task_data.assignee_id) if task_data.assignee_id else None,
            "assigneeResolvedBy": task_data.assignee_resolved_by,
            "deadlineHint": task_data.deadline_hint,
            "deadlineDate": task_data.deadline_date,
            "deadlineResolvedBy": task_data.deadline_resolved_by,
            "transcriptWordStart": task_data.transcript_word_start,
            "transcriptWordEnd": task_data.transcript_word_end,
            "sourceQuote": task_data.source_quote,
            "verificationStatus": task_data.verification_status,
            "verificationReasoning": task_data.verification_reasoning,
            "extractionConfidence": task_data.extraction_confidence,
            "externalId": task_data.external_id,
            "externalUrl": task_data.external_url,
            "integrationId": str(task_data.integration_id) if task_data.integration_id else None,
            "lastSyncedAt": task_data.last_synced_at,
            "syncStatus": task_data.sync_status,
            "createdBy": task_data.created_by,
            "status": task_data.status or "EXTRACTED",
        }
    )
    
    # Create audit log entry
    await db.taskauditlog.create(
        data={
            "taskId": task.id,
            "newStatus": task.status,
            "changedBy": task_data.created_by,
            "reason": "Task created by AI extraction",
        }
    )
    
    return task


@router.get("", response_model=PaginatedResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    meeting_id: Optional[UUID] = None,
    assignee_id: Optional[UUID] = None,
    task_status: Optional[TaskStatus] = Query(None, alias="status"),
    task_type: Optional[TaskType] = None,
    priority: Optional[Priority] = None,
    db=Depends(get_db),
):
    """List tasks with pagination and filtering."""
    where = {}
    if meeting_id:
        where["meetingId"] = str(meeting_id)
    if assignee_id:
        where["assigneeId"] = str(assignee_id)
    if task_status:
        where["status"] = task_status
    if task_type:
        where["taskType"] = task_type
    if priority:
        where["priority"] = priority
    
    total = await db.task.count(where=where)
    tasks = await db.task.find_many(
        where=where,
        skip=(page - 1) * page_size,
        take=page_size,
        order={"createdAt": "desc"},
        include={"assignee": True, "meeting": True, "integration": True},
    )
    
    return PaginatedResponse(
        items=tasks,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{task_id}", response_model=Task)
async def get_task(
    task_id: UUID,
    db=Depends(get_db),
):
    """Get a single task by ID."""
    task = await db.task.find_unique(
        where={"id": str(task_id)},
        include={"assignee": True, "meeting": True, "integration": True, "auditLogs": True},
    )
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    return task


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: UUID,
    task_data: TaskUpdate,
    db=Depends(get_db),
    changed_by: str = "api_user",
):
    """Update a task with state machine validation."""
    task = await db.task.find_unique(where={"id": str(task_id)})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    # Validate state transition
    update_data = task_data.model_dump(exclude_unset=True)
    new_status = update_data.get("status")
    
    if new_status and new_status != task.status:
        if not _is_valid_transition(task.status, new_status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition: {task.status} -> {new_status}",
            )
        
        # Create audit log
        await db.taskauditlog.create(
            data={
                "taskId": str(task_id),
                "previousStatus": task.status,
                "newStatus": new_status,
                "changedBy": changed_by,
                "reason": update_data.get("reason", "Manual status update"),
            }
        )
    
    updated = await db.task.update(
        where={"id": str(task_id)},
        data=update_data,
    )
    
    return updated


@router.post("/{task_id}/verify", response_model=Task)
async def verify_task(
    task_id: UUID,
    verification_status: VerificationStatus,
    reasoning: str = "",
    db=Depends(get_db),
    changed_by: str = "api_user",
):
    """Verify or reject a task (human-in-the-loop)."""
    task = await db.task.find_unique(where={"id": str(task_id)})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    if verification_status == VerificationStatus.VERIFIED:
        new_status = TaskStatus.VERIFIED
    elif verification_status == VerificationStatus.NEEDS_REVIEW:
        new_status = TaskStatus.PENDING_REVIEW
    elif verification_status == VerificationStatus.FAILED:
        new_status = TaskStatus.DISMISSED
    else:
        new_status = task.status
    
    updated = await db.task.update(
        where={"id": str(task_id)},
        data={
            "verificationStatus": verification_status,
            "verificationReasoning": reasoning,
            "status": new_status,
        },
    )
    
    # Audit log
    await db.taskauditlog.create(
        data={
            "taskId": str(task_id),
            "previousStatus": task.status,
            "newStatus": new_status,
            "changedBy": changed_by,
            "reason": f"Human verification: {verification_status}. {reasoning}",
        }
    )
    
    return updated


@router.post("/{task_id}/assign", response_model=Task)
async def assign_task(
    task_id: UUID,
    assignee_id: UUID,
    db=Depends(get_db),
    changed_by: str = "api_user",
):
    """Assign a task to a user."""
    task = await db.task.find_unique(where={"id": str(task_id)})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    # Verify assignee exists
    assignee = await db.user.find_unique(where={"id": str(assignee_id)})
    if not assignee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignee not found",
        )
    
    updated = await db.task.update(
        where={"id": str(task_id)},
        data={
            "assigneeId": str(assignee_id),
            "assigneeResolvedBy": "manual",
            "status": TaskStatus.ASSIGNED,
        },
    )
    
    await db.taskauditlog.create(
        data={
            "taskId": str(task_id),
            "previousStatus": task.status,
            "newStatus": TaskStatus.ASSIGNED,
            "changedBy": changed_by,
            "reason": f"Assigned to {assignee.fullName} ({assignee.email})",
        }
    )
    
    return updated


@router.post("/{task_id}/dismiss", response_model=Task)
async def dismiss_task(
    task_id: UUID,
    reason: str = "",
    db=Depends(get_db),
    changed_by: str = "api_user",
):
    """Dismiss a task."""
    task = await db.task.find_unique(where={"id": str(task_id)})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    updated = await db.task.update(
        where={"id": str(task_id)},
        data={"status": TaskStatus.DISMISSED},
    )
    
    await db.taskauditlog.create(
        data={
            "taskId": str(task_id),
            "previousStatus": task.status,
            "newStatus": TaskStatus.DISMISSED,
            "changedBy": changed_by,
            "reason": f"Dismissed: {reason}",
        }
    )
    
    return updated


@router.post("/bulk-update", response_model=List[Task])
async def bulk_update_tasks(
    task_ids: List[UUID],
    task_data: TaskUpdate,
    db=Depends(get_db),
    changed_by: str = "api_user",
):
    """Bulk update multiple tasks."""
    results = []
    for task_id in task_ids:
        task = await db.task.find_unique(where={"id": str(task_id)})
        if not task:
            continue
        
        update_data = task_data.model_dump(exclude_unset=True)
        new_status = update_data.get("status")
        
        if new_status and new_status != task.status:
            if not _is_valid_transition(task.status, new_status):
                continue
            
            await db.taskauditlog.create(
                data={
                    "taskId": str(task_id),
                    "previousStatus": task.status,
                    "newStatus": new_status,
                    "changedBy": changed_by,
                    "reason": update_data.get("reason", "Bulk update"),
                }
            )
        
        updated = await db.task.update(
            where={"id": str(task_id)},
            data=update_data,
        )
        results.append(updated)
    
    return results


@router.get("/{task_id}/audit-log", response_model=List[TaskAuditLog])
async def get_task_audit_log(
    task_id: UUID,
    db=Depends(get_db),
):
    """Get audit log for a task."""
    task = await db.task.find_unique(where={"id": str(task_id)})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    logs = await db.taskauditlog.find_many(
        where={"taskId": str(task_id)},
        order={"createdAt": "asc"},
    )
    
    return logs


# ─── State Machine Validation ───

VALID_TRANSITIONS = {
    TaskStatus.EXTRACTED: [TaskStatus.PENDING_REVIEW, TaskStatus.VERIFIED, TaskStatus.DISMISSED],
    TaskStatus.PENDING_REVIEW: [TaskStatus.VERIFIED, TaskStatus.DISMISSED],
    TaskStatus.VERIFIED: [TaskStatus.ASSIGNED, TaskStatus.PENDING_REVIEW, TaskStatus.DISMISSED],
    TaskStatus.ASSIGNED: [TaskStatus.SYNCED, TaskStatus.COMPLETED, TaskStatus.PENDING_REVIEW, TaskStatus.DISMISSED],
    TaskStatus.SYNCED: [TaskStatus.COMPLETED, TaskStatus.SYNC_FAILED, TaskStatus.CONFLICT, TaskStatus.DISMISSED],
    TaskStatus.SYNC_FAILED: [TaskStatus.SYNCED, TaskStatus.DISMISSED],
    TaskStatus.CONFLICT: [TaskStatus.SYNCED, TaskStatus.DISMISSED],
    TaskStatus.COMPLETED: [],
    TaskStatus.DISMISSED: [],
}


def _is_valid_transition(current: TaskStatus, new: TaskStatus) -> bool:
    """Check if a status transition is valid."""
    return new in VALID_TRANSITIONS.get(current, [])