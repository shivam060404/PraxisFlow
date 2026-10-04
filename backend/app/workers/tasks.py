from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.db.prisma import get_prisma
from app.services.asr import transcribe_meeting
from app.services.storage import storage_service
from app.workers.celery_app import celery_app, async_task
from app.ai.agents.schemas import TranscriptChunk
from app.ai.agents.graph_runner import run_extraction_pipeline

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
    users = await db.user.find_many(
        where={"tenantId": meeting.tenantId, "status": "ACTIVE"},
        select={"email": True},
    )
    from app.services.notifications import enqueue_meeting_notifications

    await enqueue_meeting_notifications(meeting, users, db=db)
    deliver_notifications.delay()
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
        from app.ai.guardrails.output_guardrails import HallucinationDetector
        from app.ai.guardrails.base import GuardrailAction, GuardrailContext

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
    """Enqueue integration delivery; providers are never called inline."""
    db = await get_prisma()
    
    task = await db.task.find_unique(
        where={"id": task_id},
        include={"meeting": {"include": {"tasks": True}}},
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
    
    results = []

    for integration in integrations:
        try:
            if (
                task.integrationId == integration.id
                and task.externalId
                and task.syncStatus == "SYNCED"
            ):
                results.append(
                    {
                        "integration": integration.provider,
                        "status": "already_synced",
                        "external_id": task.externalId,
                    }
                )
                continue
            from app.services.task_outbox import enqueue_task_sync

            await enqueue_task_sync(task, integration, db=db)
            await db.task.update(
                where={"id": task_id},
                data={
                    "integrationId": integration.id,
                    "syncStatus": "PENDING",
                },
            )
            relay_outbox.delay()
            results.append({"integration": integration.provider, "status": "queued"})
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

    return {"queued": len([r for r in results if r["status"] == "queued"]), "results": results}


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def relay_outbox(self):
    """Deliver pending outbox records with at-least-once semantics."""
    try:
        return run_async(_relay_outbox_async())
    except Exception as exc:
        logger.error("Outbox relay failed: %s", exc)
        raise self.retry(exc=exc)


async def _relay_outbox_async(limit: int = 50):
    db = await get_prisma()
    from app.integrations.factory import IntegrationAdapterFactory
    from app.services.task_outbox import requeue_stale_outbox_events

    await requeue_stale_outbox_events(db)
    events = await db.taskoutbox.find_many(
        where={
            "status": "PENDING",
            "availableAt": {"lte": datetime.utcnow()},
        },
        take=limit,
        order={"createdAt": "asc"},
        include={"task": {"include": {"meeting": True}}, "integration": True},
    )
    delivered = 0
    for event in events:
        claimed = await db.taskoutbox.update_many(
            where={"id": event.id, "status": "PENDING"},
            data={
                "status": "PROCESSING",
                "lockedAt": datetime.utcnow(),
                "attempts": {"increment": 1},
            },
        )
        if not claimed:
            continue
        try:
            adapter = IntegrationAdapterFactory.get_adapter(event.integration.provider)
            external_id = await adapter.create_task(event.integration, event.task)
            base_url = (event.integration.config or {}).get("base_url", "")
            external_url = (
                f"{base_url}/browse/{external_id}"
                if event.integration.provider == "jira"
                else (
                    f"https://linear.app/issue/{external_id}"
                    if event.integration.provider == "linear"
                    else f"https://app.asana.com/0/{external_id}"
                )
            )
            await db.task.update(
                where={"id": event.taskId},
                data={
                    "externalId": external_id,
                    "externalUrl": external_url,
                    "syncStatus": "SYNCED",
                    "lastSyncedAt": datetime.utcnow(),
                    "status": "SYNCED",
                },
            )
            await db.taskoutbox.update(
                where={"id": event.id},
                data={
                    "status": "SYNCED",
                    "processedAt": datetime.utcnow(),
                    "lockedAt": None,
                    "lastError": None,
                },
            )
            delivered += 1
        except Exception as exc:
            logger.exception("Outbox delivery failed for %s", event.id)
            await db.taskoutbox.update(
                where={"id": event.id},
                data={
                    "status": "PENDING",
                    "availableAt": datetime.utcnow() + timedelta(minutes=min(30, 2 ** min(event.attempts, 5))),
                    "lockedAt": None,
                    "lastError": str(exc),
                },
            )
    return {"delivered": delivered, "inspected": len(events)}


@shared_task
def requeue_stale_outbox():
    """Recover leases held by workers that terminated unexpectedly."""
    return run_async(_requeue_stale_outbox_async())


@shared_task
def requeue_stale_webhook_events():
    """Recover webhook leases held by workers that terminated unexpectedly."""
    return run_async(_requeue_stale_webhook_events_async())


@shared_task
def deliver_notifications():
    return run_async(_deliver_notifications_async())


async def _deliver_notifications_async(limit: int = 50):
    db = await get_prisma()
    from app.services.notifications import claim_delivery, deliver_notification

    deliveries = await db.notificationdelivery.find_many(
        where={"status": "PENDING", "availableAt": {"lte": datetime.utcnow()}},
        take=limit,
        order={"createdAt": "asc"},
        include={"meeting": True},
    )
    sent = 0
    for delivery in deliveries:
        if not await claim_delivery(delivery.id, db=db):
            continue
        try:
            await deliver_notification(delivery, delivery.meeting)
            await db.notificationdelivery.update(
                where={"id": delivery.id},
                data={"status": "SENT", "sentAt": datetime.utcnow(), "lastError": None},
            )
            sent += 1
        except Exception as exc:
            logger.exception("Notification delivery failed for %s", delivery.id)
            terminal = delivery.attempts >= 5
            await db.notificationdelivery.update(
                where={"id": delivery.id},
                data={
                    "status": "DEAD_LETTER" if terminal else "PENDING",
                    "availableAt": datetime.utcnow() + timedelta(minutes=min(30, 2 ** min(delivery.attempts, 5))),
                    "lastError": str(exc),
                },
            )
    return {"sent": sent, "inspected": len(deliveries)}


@shared_task
def requeue_stale_notifications():
    return run_async(_requeue_stale_notifications_async())


async def _requeue_stale_notifications_async():
    db = await get_prisma()
    from app.services.notifications import requeue_stale_notifications as requeue

    return {"requeued": await requeue(db)}


@shared_task
def schedule_upcoming_captures():
    """Schedule capture bots for meetings starting within the next 15 minutes."""
    return run_async(_schedule_upcoming_captures_async())


async def _schedule_upcoming_captures_async():
    from app.core.config import settings
    from app.services.meeting_capture import schedule_recall_capture

    if not settings.CAPTURE_SCHEDULER_ENABLED:
        return {"status": "disabled", "scheduled": 0}
    db = await get_prisma()
    now = datetime.utcnow()
    horizon = now + timedelta(minutes=15)
    meetings = await db.meeting.find_many(
        where={
            "status": "SCHEDULED",
            "scheduledAt": {"gte": now, "lte": horizon},
            "consentStatus": "granted",
            "captures": {
                "none": {
                    "status": {
                        "in": ["SCHEDULING", "SCHEDULED", "JOINING", "IN_PROGRESS", "COMPLETED"]
                    }
                }
            },
        },
        include={"calendarEvent": True, "tenant": True},
        take=100,
    )
    scheduled = 0
    failed = 0
    for meeting in meetings:
        try:
            try:
                lease = await db.meetingcapture.find_first(
                    where={"meetingId": meeting.id, "provider": "recall", "status": "FAILED"}
                )
                if lease:
                    await db.meetingcapture.update(
                        where={"id": lease.id},
                        data={"status": "SCHEDULING", "lastAttemptAt": datetime.utcnow()},
                    )
                else:
                    await db.meetingcapture.create(
                        data={
                            "tenantId": meeting.tenantId,
                            "meetingId": meeting.id,
                            "provider": "recall",
                            "externalBotId": f"pending:{meeting.id}",
                            "webhookSecret": "pending",
                            "scheduledFor": meeting.scheduledAt,
                            "status": "SCHEDULING",
                        }
                    )
            except Exception:
                # A competing scheduler already owns the meeting lease.
                continue
            await schedule_recall_capture(meeting, db=db)
            scheduled += 1
        except Exception as exc:
            failed += 1
            logger.exception("Capture scheduling failed for meeting %s: %s", meeting.id, exc)
            await db.meetingcapture.update_many(
                where={
                    "meetingId": meeting.id,
                    "provider": "recall",
                    "status": "SCHEDULING",
                },
                data={
                    "status": "FAILED",
                    "errorMessage": str(exc),
                    "lastAttemptAt": datetime.utcnow(),
                    "attempts": {"increment": 1},
                },
            )
    return {"status": "completed", "scheduled": scheduled, "failed": failed}


async def _requeue_stale_webhook_events_async():
    db = await get_prisma()
    from app.services.webhook_events import requeue_stale_webhook_events as requeue

    return {"requeued": await requeue(db)}


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def process_webhook_event(self, event_id: str):
    """Apply one durable webhook event with retry and dead-letter semantics."""
    try:
        return run_async(_process_webhook_event_async(event_id))
    except Exception as exc:
        logger.exception("Webhook event processing failed for %s", event_id)
        try:
            return self.retry(exc=exc)
        except MaxRetriesExceededError:
            return run_async(_dead_letter_webhook_event(event_id, str(exc)))


async def _process_webhook_event_async(event_id: str):
    db = await get_prisma()
    event = await db.integrationwebhookevent.find_unique(
        where={"id": event_id},
        include={"integration": True},
    )
    if not event:
        raise ValueError(f"Webhook event not found: {event_id}")
    if event.status == "PROCESSED":
        return {"status": "already_processed", "event_id": event_id}

    from app.integrations.factory import IntegrationAdapterFactory
    from app.services.webhook_events import claim_webhook_event

    if not await claim_webhook_event(event_id, db=db):
        return {"status": "already_claimed", "event_id": event_id}

    try:
        adapter = IntegrationAdapterFactory.get_adapter(event.provider)
        normalized = adapter.normalize_webhook(event.payload)
        task = await db.task.find_first(
            where={
                "externalId": normalized.external_id,
                "integrationId": event.integrationId,
                "tenantId": event.tenantId,
            }
        )
        if task:
            new_status = _map_external_status(event.provider, normalized.status or "")
            if new_status != task.status:
                await db.task.update(
                    where={"id": task.id},
                    data={
                        "status": new_status,
                        "syncStatus": "SYNCED",
                        "lastSyncedAt": normalized.changed_at,
                    },
                )
                await db.taskauditlog.create(
                    data={
                        "taskId": task.id,
                        "previousStatus": task.status,
                        "newStatus": new_status,
                        "changedBy": f"webhook_{event.provider}",
                        "reason": f"External status update from {event.provider}: {normalized.status}",
                        "metadata": {"webhook_event_id": event.id},
                    }
                )

        await db.integrationwebhookevent.update(
            where={"id": event.id},
            data={
                "status": "PROCESSED",
                "processedAt": datetime.utcnow(),
                "lockedAt": None,
                "lastError": None,
            },
        )
        return {"status": "processed", "task_found": bool(task), "event_id": event_id}
    except Exception as exc:
        await db.integrationwebhookevent.update(
            where={"id": event.id},
            data={
                "status": "PENDING",
                "availableAt": datetime.utcnow() + timedelta(minutes=min(30, 2 ** min(event.attempts, 5))),
                "lockedAt": None,
                "lastError": str(exc),
            },
        )
        raise


async def _dead_letter_webhook_event(event_id: str, error: str):
    db = await get_prisma()
    await db.integrationwebhookevent.update(
        where={"id": event_id},
        data={"status": "DEAD_LETTER", "lockedAt": None, "lastError": error},
    )
    return {"status": "dead_letter", "event_id": event_id}


async def _requeue_stale_outbox_async():
    db = await get_prisma()
    from app.services.task_outbox import requeue_stale_outbox_events

    return {"requeued": await requeue_stale_outbox_events(db)}


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


@shared_task
def enforce_retention_policies():
    """Remove expired transcript/audio payloads without deleting audit records."""
    return run_async(_enforce_retention_policies_async())


@shared_task
def reconcile_external_tasks(limit: int = 100):
    """Run optional provider reconciliation hooks for durable task records."""
    return run_async(_reconcile_external_tasks_async(limit))


async def _reconcile_external_tasks_async(limit: int = 100):
    db = await get_prisma()
    from app.integrations.factory import IntegrationAdapterFactory

    tasks = await db.task.find_many(
        where={
            "tenantId": {"not": None},
            "externalId": {"not": None},
            "integrationId": {"not": None},
        },
        include={"integration": True},
        take=limit,
        order={"updatedAt": "asc"},
    )
    reconciled = 0
    failed = 0
    missing = 0
    for task in tasks:
        integration = task.integration
        if not integration:
            continue
        adapter, config = IntegrationAdapterFactory.create_adapter(integration)
        # Only invoke providers that explicitly implement the hook.
        from app.integrations.base import IntegrationPort
        if type(adapter).reconcile_task is IntegrationPort.reconcile_task:
            continue
        try:
            state = await adapter.reconcile_task(config, task)
        except Exception:
            failed += 1
            logger.exception("External task reconciliation failed for %s", task.id)
            await db.task.update(where={"id": task.id}, data={"syncStatus": "SYNC_FAILED"})
            continue
        if not state:
            continue
        if state.get("missing"):
            missing += 1
            await db.task.update(where={"id": task.id}, data={"syncStatus": "SYNC_FAILED"})
            continue
        data = {}
        if state.get("external_url"):
            data["externalUrl"] = state["external_url"]
        if state.get("status"):
            data["status"] = _map_reconciled_status(state["status"])
            data["syncStatus"] = "SYNCED"
            data["lastSyncedAt"] = datetime.utcnow()
        if data:
            await db.task.update(where={"id": task.id}, data=data)
            reconciled += 1
    return {"inspected": len(tasks), "reconciled": reconciled, "missing": missing, "failed": failed}


def _map_reconciled_status(status: str) -> str:
    """Map adapter-normalized status to the local task enum."""
    return {
        "todo": "EXTRACTED",
        "in_progress": "ASSIGNED",
        "in_review": "SYNCED",
        "done": "COMPLETED",
        "cancelled": "DISMISSED",
    }.get(status, "SYNCED")


def _map_external_status(provider: str, status: str) -> str:
    """Normalize webhook and reconciliation statuses consistently."""
    normalized = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "to_do": "todo", "new": "todo", "backlog": "todo", "unstarted": "todo",
        "started": "in_progress", "working": "in_progress",
        "review": "in_review", "completed": "done", "closed": "done",
        "resolved": "done", "canceled": "cancelled",
    }
    return _map_reconciled_status(aliases.get(normalized, normalized))


async def _enforce_retention_policies_async():
    db = await get_prisma()
    tenants = await db.tenant.find_many(
        select={"id": True, "retentionDays": True}
    )
    deleted_transcripts = 0
    deleted_audio = 0
    deleted_notifications = 0
    deleted_webhooks = 0
    deleted_audit_logs = 0
    for tenant in tenants:
        cutoff = datetime.utcnow() - timedelta(days=tenant.retentionDays)
        meetings = await db.meeting.find_many(
            where={
                "tenantId": tenant.id,
                "updatedAt": {"lt": cutoff},
                "transcript": {"isNot": None},
            },
            select={"id": True, "audioUrl": True},
            take=500,
        )
        for meeting in meetings:
            audio_deleted = False
            if meeting.audioUrl:
                try:
                    audio_deleted = await storage_service.delete_file(meeting.audioUrl)
                    if audio_deleted:
                        deleted_audio += 1
                except Exception:
                    logger.exception("Retention deletion failed for audio on %s", meeting.id)
            deleted = await db.transcript.delete_many(
                where={"meetingId": meeting.id}
            )
            deleted_transcripts += deleted
            # Clear the durable reference after deleting the object so retries
            # do not repeatedly attempt the same retention deletion.
            if meeting.audioUrl and audio_deleted:
                await db.meeting.update(
                    where={"id": meeting.id},
                    data={"audioUrl": None},
                )
        # Delivery and inbound webhook payloads can contain meeting/task
        # content and must follow the same tenant-specific retention window.
        deleted_notifications += await db.notificationdelivery.delete_many(
            where={"tenantId": tenant.id, "createdAt": {"lt": cutoff}}
        )
        deleted_webhooks += await db.integrationwebhookevent.delete_many(
            where={"tenantId": tenant.id, "createdAt": {"lt": cutoff}}
        )
        deleted_audit_logs += await db.taskauditlog.delete_many(
            where={"task": {"tenantId": tenant.id}, "createdAt": {"lt": cutoff}}
        )
        deleted_audit_logs += await db.aiauditlog.delete_many(
            where={"tenantId": tenant.id, "createdAt": {"lt": cutoff}}
        )
    return {
        "transcripts_deleted": deleted_transcripts,
        "audio_objects_deleted": deleted_audio,
        "notifications_deleted": deleted_notifications,
        "webhook_payloads_deleted": deleted_webhooks,
        "audit_logs_deleted": deleted_audit_logs,
    }