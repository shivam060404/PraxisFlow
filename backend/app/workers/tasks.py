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
from app.agents.schemas import TranscriptChunk
from app.agents.graph_runner import run_extraction_pipeline_wrapper

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
    
    # Update status to PROCESSING
    await db.meeting.update(
        where={"id": meeting_id},
        data={"status": "PROCESSING"},
    )
    
    # Build transcript chunks from utterances for the LangGraph pipeline
    transcript_chunks = []
    if transcript.utterances:
        for i, utt in enumerate(transcript.utterances):
            transcript_chunks.append(TranscriptChunk(
                index=i,
                text=utt.text,
                word_start=utt.wordStartIdx or 0,
                word_end=utt.wordEndIdx or 0,
                speakers=[utt.speakerLabel],
            ))
    else:
        # Fallback: treat full text as a single chunk
        words = transcript.fullText.split()
        transcript_chunks.append(TranscriptChunk(
            index=0,
            text=transcript.fullText,
            word_start=0,
            word_end=len(words) - 1,
            speakers=["Unknown"],
        ))
    
    # Get a user_id for the pipeline (use meeting organizer or first attendee)
    user_id = meeting.organizerId
    if not user_id and meeting.attendees:
        user_id = meeting.attendees[0].userId
    if not user_id:
        # Fallback: get any user from tenant
        any_user = await db.user.find_first(where={"tenantId": meeting.tenantId})
        user_id = any_user.id if any_user else meeting.tenantId
    
    # Run the full LangGraph extraction pipeline
    # This runs: chunking → extraction → dedup → verification → entity_resolution → persistence
    final_state = await run_extraction_pipeline_wrapper(
        meeting_id=meeting_id,
        tenant_id=meeting.tenantId,
        user_id=user_id,
        meeting_context=f"Meeting: {meeting.title}",
        transcript_chunks=transcript_chunks,
    )
    
    # The persistence_node in the graph already creates Task records and
    # updates the meeting status to EXTRACTED. Now queue verification
    # for any tasks that need it (NEEDS_REVIEW from pipeline).
    tasks = await db.task.find_many(
        where={"meetingId": meeting_id, "verificationStatus": "NEEDS_REVIEW"},
    )
    for task in tasks:
        verify_task.delay(task.id)
    
    task_count = len(final_state.final_tasks) if final_state.final_tasks else 0
    logger.info(f"Extraction pipeline created {task_count} tasks for meeting {meeting_id}")
    
    # Check if pipeline was interrupted for HITL
    if final_state.interrupted:
        logger.info(f"Pipeline interrupted for HITL: {meeting_id}, reason: {final_state.interrupt_reason}")
        # Emit event for frontend notification
        from app.services.kafka_events import kafka_event_publisher
        await kafka_event_publisher.publish("hitl-events", {
            "type": "pipeline.interrupted",
            "meeting_id": meeting_id,
            "tenant_id": meeting.tenantId,
            "payload": {
                "interrupt_node": final_state.interrupt_node,
                "interrupt_reason": final_state.interrupt_reason,
                "interrupt_payload": final_state.interrupt_payload,
            },
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    return {"tasks_created": task_count, "meeting_id": meeting_id}


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
    """Async integration sync using adapter pattern."""
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
    
    if not integrations:
        logger.info(f"No active integrations for tenant {task.tenantId}, skipping sync")
        return {"synced": 0, "results": []}
    
    from app.integrations.factory import IntegrationAdapterFactory
    
    results = []
    
    for integration in integrations:
        try:
            adapter = IntegrationAdapterFactory.get_adapter(integration.provider)
            
            # Create task in external system
            external_id = await adapter.create_task(integration, task)
            
            # Build external URL based on provider
            external_url = ""
            if integration.provider == "jira":
                base_url = integration.config.get("base_url", "")
                external_url = f"{base_url}/browse/{external_id}"
            elif integration.provider == "linear":
                external_url = f"https://linear.app/issue/{external_id}"
            elif integration.provider == "asana":
                external_url = f"https://app.asana.com/0/{external_id}"
            
            # Update task with real external ID
            await db.task.update(
                where={"id": task_id},
                data={
                    "integrationId": integration.id,
                    "externalId": external_id,
                    "externalUrl": external_url,
                    "syncStatus": "SYNCED",
                    "lastSyncedAt": datetime.utcnow(),
                    "status": "SYNCED",
                },
            )
            
            logger.info(f"Synced task {task_id} to {integration.provider} as {external_id}")
            
            results.append({
                "integration": integration.provider,
                "status": "synced",
                "external_id": external_id,
            })
            
        except Exception as e:
            logger.error(f"Failed to sync to {integration.provider}: {e}")
            
            await db.task.update(
                where={"id": task_id},
                data={"syncStatus": "SYNC_FAILED"},
            )
            
            results.append({
                "integration": integration.provider,
                "status": "failed",
                "error": str(e),
            })
    
    return {"synced": len([r for r in results if r["status"] == "synced"]), "results": results}


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