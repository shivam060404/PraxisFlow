from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.db.prisma import get_prisma
from app.services.asr import transcribe_meeting
from app.services.storage import storage_service
from app.workers.celery_app import celery_app, async_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_meeting(self, meeting_id: str):
    """Process a meeting: transcribe -> extract -> verify -> resolve."""
    logger.info(f"Starting meeting processing: {meeting_id}")
    
    try:
        result = asyncio.run(_process_meeting_async(meeting_id))
        logger.info(f"Meeting processing completed: {meeting_id}")
        return result
    except Exception as e:
        logger.error(f"Meeting processing failed: {meeting_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            # Mark meeting as error
            asyncio.run(_mark_meeting_error(meeting_id, str(e)))
            raise


async def _process_meeting_async(meeting_id: str):
    """Async meeting processing pipeline."""
    db = await get_prisma()
    
    # Get meeting
    meeting = await db.meeting.find_unique(where={"id": meeting_id})
    if not meeting:
        raise ValueError(f"Meeting not found: {meeting_id}")
    
    # Update status
    await db.meeting.update(
        where={"id": meeting_id},
        data={"status": "PROCESSING"},
    )
    
    # Step 1: Transcribe (if not already transcribed)
    if meeting.status in ["UPLOADED", "PROCESSING"]:
        transcript = await transcribe_meeting(
            audio_url=meeting.audioUrl,
            meeting_id=meeting_id,
            tenant_id=meeting.tenantId,
        )
        
        # Update meeting status
        await db.meeting.update(
            where={"id": meeting_id},
            data={"status": "TRANSCRIBED"},
        )
    
    # Step 2: Run extraction pipeline
    from app.workers.tasks import run_extraction
    run_extraction.delay(meeting_id)
    
    return {"status": "transcribed", "meeting_id": meeting_id}


async def _mark_meeting_error(meeting_id: str, error: str):
    """Mark meeting as error."""
    db = await get_prisma()
    await db.meeting.update(
        where={"id": meeting_id},
        data={
            "status": "ERROR",
            # Add error field if exists in schema
        },
    )
    
    # Create meeting flag
    await db.meetingflag.create(
        data={
            "meetingId": meeting_id,
            "flagType": "PROCESSING_FAILED",
            "message": error,
        }
    )


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def run_extraction(self, meeting_id: str):
    """Run the LangGraph extraction pipeline."""
    logger.info(f"Running extraction for meeting: {meeting_id}")
    
    try:
        result = asyncio.run(_run_extraction_async(meeting_id))
        logger.info(f"Extraction completed: {meeting_id}")
        return result
    except Exception as e:
        logger.error(f"Extraction failed: {meeting_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            asyncio.run(_mark_extraction_failed(meeting_id, str(e)))
            raise


async def _run_extraction_async(meeting_id: str):
    """Async extraction pipeline using LangGraph."""
    db = await get_prisma()
    
    # Get meeting with transcript
    meeting = await db.meeting.find_unique(
        where={"id": meeting_id},
        include={"transcript": {"include": {"utterances": True}}},
    )
    
    if not meeting or not meeting.transcript:
        raise ValueError("Meeting or transcript not found")
    
    transcript = meeting.transcript
    
    # Update status
    await db.meeting.update(
        where={"id": meeting_id},
        data={"status": "EXTRACTED"},
    )
    
    # TODO: Implement LangGraph extraction pipeline
    # For now, create placeholder tasks
    
    # Create a sample task
    task = await db.task.create(
        data={
            "tenantId": meeting.tenantId,
            "meetingId": meeting_id,
            "title": "Review quarterly budget",
            "description": "Review and approve Q1 budget allocations discussed in meeting",
            "taskType": "ACTION_ITEM",
            "status": "EXTRACTED",
            "priority": "HIGH",
            "assigneeHint": "Sarah from finance",
            "deadlineHint": "by Friday",
            "transcriptWordStart": 100,
            "transcriptWordEnd": 150,
            "sourceQuote": "Sarah, can you review the quarterly budget by Friday?",
            "extractionConfidence": 0.85,
            "verificationStatus": "PENDING",
            "createdBy": "ai_agent",
        }
    )
    
    # Queue verification
    verify_task.delay(task.id)
    
    return {"tasks_created": 1, "meeting_id": meeting_id}


async def _mark_extraction_failed(meeting_id: str, error: str):
    """Mark extraction as failed."""
    db = await get_prisma()
    await db.meetingflag.create(
        data={
            "meetingId": meeting_id,
            "flagType": "EXTRACTION_FAILED",
            "message": error,
        }
    )


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def verify_task(self, task_id: str):
    """Run verification agent on a task."""
    logger.info(f"Verifying task: {task_id}")
    
    try:
        result = asyncio.run(_verify_task_async(task_id))
        logger.info(f"Verification completed: {task_id}")
        return result
    except Exception as e:
        logger.error(f"Verification failed: {task_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            asyncio.run(_mark_verification_failed(task_id, str(e)))
            raise


async def _verify_task_async(task_id: str):
    """Async task verification."""
    db = await get_prisma()
    
    task = await db.task.find_unique(
        where={"id": task_id},
        include={"meeting": {"include": {"transcript": True}}},
    )
    
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    
    # TODO: Implement verification agent
    # For now, mark as verified
    
    await db.task.update(
        where={"id": task_id},
        data={
            "verificationStatus": "VERIFIED",
            "verificationReasoning": "Auto-verified (placeholder)",
            "status": "VERIFIED",
        },
    )
    
    # Create audit log
    await db.taskauditlog.create(
        data={
            "taskId": task_id,
            "previousStatus": "EXTRACTED",
            "newStatus": "VERIFIED",
            "changedBy": "verification_agent",
            "reason": "Passed verification",
        }
    )
    
    # Trigger entity resolution
    resolve_assignee.delay(task_id)
    
    return {"verified": True, "task_id": task_id}


async def _mark_verification_failed(task_id: str, error: str):
    """Mark verification as failed."""
    db = await get_prisma()
    await db.task.update(
        where={"id": task_id},
        data={
            "verificationStatus": "NEEDS_REVIEW",
            "verificationReasoning": f"Verification failed: {error}",
            "status": "PENDING_REVIEW",
        },
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def resolve_assignee(self, task_id: str):
    """Resolve assignee hint to actual user."""
    logger.info(f"Resolving assignee for task: {task_id}")
    
    try:
        result = asyncio.run(_resolve_assignee_async(task_id))
        logger.info(f"Assignee resolution completed: {task_id}")
        return result
    except Exception as e:
        logger.error(f"Assignee resolution failed: {task_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            asyncio.run(_mark_resolution_failed(task_id, str(e)))
            raise


async def _resolve_assignee_async(task_id: str):
    """Async assignee resolution."""
    db = await get_prisma()
    
    task = await db.task.find_unique(
        where={"id": task_id},
        include={"meeting": {"include": {"attendees": True}}},
    )
    
    if not task or not task.assigneeHint:
        return {"resolved": False, "reason": "No assignee hint"}
    
    # Simple fuzzy match against attendees
    from rapidfuzz import fuzz
    
    best_match = None
    best_score = 0
    
    for attendee in task.meeting.attendees:
        if not attendee.displayName:
            continue
        
        score = fuzz.partial_ratio(
            task.assigneeHint.lower(),
            attendee.displayName.lower(),
        )
        
        if score > best_score and score >= 80:
            best_score = score
            best_match = attendee
    
    if best_match and best_match.userId:
        # Update task with resolved assignee
        await db.task.update(
            where={"id": task_id},
            data={
                "assigneeId": best_match.userId,
                "assigneeResolvedBy": "entity_resolution_agent",
                "status": "ASSIGNED",
            },
        )
        
        await db.taskauditlog.create(
            data={
                "taskId": task_id,
                "previousStatus": "VERIFIED",
                "newStatus": "ASSIGNED",
                "changedBy": "entity_resolution_agent",
                "reason": f"Resolved assignee: {best_match.displayName}",
            }
        )
        
        # Trigger sync to integrations
        sync_task_to_integrations.delay(task_id)
        
        return {"resolved": True, "assignee_id": best_match.userId}
    
    return {"resolved": False, "reason": "No confident match"}


async def _mark_resolution_failed(task_id: str, error: str):
    """Mark resolution as failed."""
    db = await get_prisma()
    await db.task.update(
        where={"id": task_id},
        data={
            "status": "PENDING_REVIEW",
            "verificationReasoning": f"Could not resolve assignee: {error}",
        },
    )


@shared_task(bind=True, max_retries=5, default_retry_delay=300)
def sync_task_to_integrations(self, task_id: str):
    """Sync verified task to external integrations."""
    logger.info(f"Syncing task to integrations: {task_id}")
    
    try:
        result = asyncio.run(_sync_task_async(task_id))
        logger.info(f"Sync completed: {task_id}")
        return result
    except Exception as e:
        logger.error(f"Sync failed: {task_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            asyncio.run(_mark_sync_failed(task_id, str(e)))
            raise


async def _sync_task_async(task_id: str):
    """Async integration sync."""
    db = await get_prisma()
    
    task = await db.task.find_unique(
        where={"id": task_id},
        include={"meeting": True},
    )
    
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    
    # Get active integrations for tenant
    integrations = await db.integration.find_many(
        where={"tenantId": task.tenantId, "status": "ACTIVE"},
    )
    
    results = []
    
    for integration in integrations:
        try:
            # TODO: Implement adapter pattern for each integration
            # For now, just log
            logger.info(f"Would sync task {task_id} to {integration.provider}")
            
            # Update task with external ID (placeholder)
            await db.task.update(
                where={"id": task_id},
                data={
                    "integrationId": integration.id,
                    "externalId": f"PLACEHOLDER-{task_id[:8]}",
                    "syncStatus": "SYNCED",
                    "lastSyncedAt": datetime.utcnow(),
                    "status": "SYNCED",
                },
            )
            
            results.append({
                "integration": integration.provider,
                "status": "synced",
            })
            
        except Exception as e:
            logger.error(f"Failed to sync to {integration.provider}: {e}")
            results.append({
                "integration": integration.provider,
                "status": "failed",
                "error": str(e),
            })
    
    return {"synced": len(results), "results": results}


async def _mark_sync_failed(task_id: str, error: str):
    """Mark sync as failed."""
    db = await get_prisma()
    await db.task.update(
        where={"id": task_id},
        data={
            "syncStatus": "SYNC_FAILED",
        },
    )


@shared_task
def retry_failed_sync(task_id: str, integration_id: str):
    """Retry a failed sync."""
    return asyncio.run(_sync_task_async(task_id))


@shared_task
def cleanup_old_data():
    """Periodic cleanup task."""
    logger.info("Running periodic cleanup")
    # TODO: Implement cleanup of old transcripts, audit logs, etc.
    return {"status": "completed"}