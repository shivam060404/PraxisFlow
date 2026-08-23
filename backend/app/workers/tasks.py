from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.db.prisma import get_prisma
from app.services.asr import transcribe_meeting
from app.services.storage import storage_service
from app.workers.celery_app import celery_app, async_task
from app.agents.schemas import TranscriptChunk
from app.agents.graph_runner import run_extraction_pipeline

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    return loop.run_until_complete(coro)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_meeting(self, meeting_id: str):
    """Process a meeting: transcribe -> extract -> verify -> resolve."""
    logger.info(f"Starting meeting processing: {meeting_id}")
    
    try:
        result = run_async(_process_meeting_async(meeting_id))
        logger.info(f"Meeting processing completed: {meeting_id}")
        return result
    except Exception as e:
        logger.error(f"Meeting processing failed: {meeting_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            # Mark meeting as error
            run_async(_mark_meeting_error(meeting_id, str(e)))
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
        # Check if transcript already exists (e.g. on retry)
        existing_transcript = await db.transcript.find_first(where={"meetingId": meeting_id})
        if not existing_transcript:
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
        else:
            logger.info(f"Transcript already exists for meeting {meeting_id}, skipping transcription")
    
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
        result = run_async(_run_extraction_async(meeting_id))
        logger.info(f"Extraction completed: {meeting_id}")
        return result
    except Exception as e:
        logger.error(f"Extraction failed: {meeting_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            run_async(_mark_extraction_failed(meeting_id, str(e)))
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
    user_id = getattr(meeting, 'organizerId', None)
    if not user_id and getattr(meeting, 'attendees', None):
        user_id = meeting.attendees[0].userId
    if not user_id:
        # Fallback: get any user from tenant
        any_user = await db.user.find_first(where={"tenantId": meeting.tenantId})
        user_id = any_user.id if any_user else meeting.tenantId
    
    # Run the full LangGraph extraction pipeline
    # This runs: chunking → extraction → dedup → verification → entity_resolution → persistence
    final_state = await run_extraction_pipeline(
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
    
    task_count = len(final_state.get("final_tasks", [])) if final_state.get("final_tasks") else 0
    logger.info(f"Extraction pipeline created {task_count} tasks for meeting {meeting_id}")
    
    # Check if pipeline was interrupted for HITL
    if final_state.get("interrupted"):
        logger.info(f"Pipeline interrupted for HITL: {meeting_id}, reason: {final_state.get('interrupt_reason')}")
        # Emit event for frontend notification
        from app.services.kafka_events import kafka_event_publisher
        await kafka_event_publisher.publish("hitl-events", {
            "type": "pipeline.interrupted",
            "meeting_id": meeting_id,
            "tenant_id": meeting.tenantId,
            "payload": {
                "interrupt_node": final_state.get("interrupt_node"),
                "interrupt_reason": final_state.get("interrupt_reason"),
                "interrupt_payload": final_state.get("interrupt_payload"),
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
        result = run_async(_verify_task_async(task_id))
        logger.info(f"Verification completed: {task_id}")
        return result
    except Exception as e:
        logger.error(f"Verification failed: {task_id}, error: {e}")
        
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            run_async(_mark_verification_failed(task_id, str(e)))
            raise


async def _verify_task_async(task_id: str):
    """Ground the extracted task against its meeting transcript.

    Uses the guardrails HallucinationDetector (keyword-overlap faithfulness
    heuristic) to decide VERIFIED vs NEEDS_REVIEW. Tasks that fail grounding
    are never silently auto-approved.
    """
    db = await get_prisma()

    task = await db.task.find_unique(
        where={"id": task_id},
        include={"meeting": {"include": {"transcript": True}}},
    )

    if not task:
        raise ValueError(f"Task not found: {task_id}")

    transcript = (
        task.meeting.transcript.fullText
        if task.meeting and task.meeting.transcript
        else None
    )

    verification_status = "NEEDS_REVIEW"
    new_status = "PENDING_REVIEW"
    reasoning = "No transcript available for grounding check; routed to human review."

    if transcript:
        from app.guardrails.output_guardrails import HallucinationDetector
        from app.guardrails.base import GuardrailAction, GuardrailContext

        detector = HallucinationDetector(enabled=True, faithfulness_threshold=0.7)
        context = GuardrailContext(tenant_id=task.tenantId, user_id="system", meeting_id=task.meetingId)
        context.transcript_context = transcript

        output = json.dumps({
            "tasks": [{
                "title": task.title,
                "description": task.description,
                "source_quote": task.sourceQuote,
            }]
        })
        result = await detector.check(output, context)

        metadata = result.metadata or {}
        faithfulness = metadata.get("faithfulness_score")
        hallucination = metadata.get("hallucination_score")

        if result.action == GuardrailAction.ALLOW:
            verification_status = "VERIFIED"
            new_status = "VERIFIED"
            reasoning = (
                f"Grounding check passed "
                f"(faithfulness={faithfulness:.2f}, hallucination={hallucination:.2f}). "
                f"Quote supported by transcript."
            )
        else:
            reasoning = (
                f"Grounding check failed ({result.message}); "
                f"faithfulness={faithfulness}, hallucination={hallucination}. "
                f"Routed to human review."
            )

    await db.task.update(
        where={"id": task_id},
        data={
            "verificationStatus": verification_status,
            "verificationReasoning": reasoning,
            "status": new_status,
        },
    )

    # Create audit log
    await db.taskauditlog.create(
        data={
            "taskId": task_id,
            "previousStatus": task.status,
            "newStatus": new_status,
            "changedBy": "verification_agent",
            "reason": reasoning,
        }
    )

    # Only resolve assignees for verified tasks
    if verification_status == "VERIFIED":
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


async def _sync_task_async(task_id: str, integration_id: str = None):
    """Async integration sync using adapter pattern."""
    db = await get_prisma()
    
    task = await db.task.find_unique(
        where={"id": task_id},
        include={"meeting": True},
    )
    
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    
    # Get active integrations for tenant (optionally scoped to one)
    integration_where = {
        "tenantId": task.tenantId,
        "status": "ACTIVE",
    }
    if integration_id:
        integration_where["id"] = integration_id
    integrations = await db.integration.find_many(
        where=integration_where,
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
def retry_failed_sync(task_id: str, integration_id: str = None):
    """Retry a failed sync, optionally scoped to one integration."""
    return asyncio.run(_sync_task_async(task_id, integration_id))


@shared_task
def cleanup_old_data():
    """Prune audit data past the retention window (default 7 years)."""
    from datetime import datetime, timedelta

    async def _cleanup():
        db = await get_prisma()
        cutoff = datetime.utcnow() - timedelta(
            days=getattr(settings, "AUDIT_RETENTION_DAYS", 2555)
        )
        logs = await db.taskauditlog.delete_many(where={"createdAt": {"lt": cutoff}})
        ai_logs = await db.aiauditlog.delete_many(where={"createdAt": {"lt": cutoff}})
        logger.info(f"Cleanup removed {logs} task audit logs, {ai_logs} AI audit logs")
        return {"taskAuditLogsDeleted": logs, "aiAuditLogsDeleted": ai_logs}

    result = run_async(_cleanup())
    logger.info("Periodic cleanup completed")
    return result