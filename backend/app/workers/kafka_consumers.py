import asyncio
import logging
from typing import Callable, Awaitable, Dict, Any

from app.services.kafka_events import kafka_event_bus, Topics
from app.workers.celery_app import celery_app
from app.workers.tasks import (
    process_meeting, 
    run_extraction, 
    verify_task, 
    resolve_assignee, 
    sync_task_to_integrations,
    retry_failed_sync
)

logger = logging.getLogger(__name__)


class KafkaConsumerManager:
    """
    DEPRECATED: Kafka-based event orchestration.

    Celery is the single task orchestrator; the API process no longer starts
    these consumers (they duplicated worker work and multiplied per uvicorn
    worker). Retained for reference / opt-in re-enablement only.
    """
    
    def __init__(self):
        self.consumers = []
        self.running = False
    
    async def start_all(self):
        """Start all consumers."""
        self.running = True
        
        # Initialize producer
        await kafka_event_bus.initialize()
        
        # Create consumers for each topic
        consumers_config = [
            {
                "topics": [Topics.MEETING_UPLOADED],
                "group_id": "ami-asr-worker",
                "handler": self.handle_meeting_uploaded,
            },
            {
                "topics": [Topics.TRANSCRIPT_COMPLETED],
                "group_id": "ami-extraction-worker",
                "handler": self.handle_transcript_completed,
            },
            {
                "topics": [Topics.TASK_VERIFIED],
                "group_id": "ami-entity-resolution-worker",
                "handler": self.handle_task_verified,
            },
            {
                "topics": [Topics.TASK_ASSIGNED],
                "group_id": "ami-sync-worker",
                "handler": self.handle_task_assigned,
            },
            {
                "topics": [Topics.TASK_SYNC_REQUESTED],
                "group_id": "ami-sync-worker",
                "handler": self.handle_sync_requested,
            },
            {
                "topics": [Topics.INTEGRATION_WEBHOOK_RECEIVED],
                "group_id": "ami-webhook-worker",
                "handler": self.handle_integration_webhook,
            },
        ]
        
        for config in consumers_config:
            consumer = kafka_event_bus.create_consumer(
                topics=config["topics"],
                group_id=config["group_id"],
                handler=config["handler"],
            )
            self.consumers.append(consumer)
        
        # Start consuming
        for consumer in self.consumers:
            await consumer.start()
            asyncio.create_task(self._consume_loop(consumer))
        
        logger.info(f"Started {len(self.consumers)} Kafka consumers")
    
    async def stop_all(self):
        """Stop all consumers."""
        self.running = False
        
        for consumer in self.consumers:
            await consumer.stop()
        
        await kafka_event_bus.close()
        logger.info("Stopped all Kafka consumers")
    
    async def _consume_loop(self, consumer):
        """Main consume loop for a consumer."""
        try:
            async for message in consumer:
                if not self.running:
                    break
                
                try:
                    await consumer._handler(message.value)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Don't re-raise - let the consumer continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Consumer loop error: {e}")
    
    # Event handlers
    
    async def handle_meeting_uploaded(self, event: Dict[str, Any]):
        """Handle meeting uploaded event - trigger ASR."""
        meeting_id = event.get("meeting_id")
        tenant_id = event.get("tenant_id")
        
        logger.info(f"Processing meeting uploaded: {meeting_id}")
        
        # Queue ASR task via Celery
        process_meeting.delay(meeting_id)
    
    async def handle_transcript_completed(self, event: Dict[str, Any]):
        """Handle transcript completed - trigger extraction."""
        meeting_id = event.get("meeting_id")
        
        logger.info(f"Transcript completed for meeting: {meeting_id}")
        
        # Queue extraction task
        run_extraction.delay(meeting_id)
    
    async def handle_task_verified(self, event: Dict[str, Any]):
        """Handle task verified - trigger entity resolution."""
        task_id = event.get("task_id")
        status = event.get("verification_status")
        
        if status == "VERIFIED":
            logger.info(f"Task verified, resolving assignee: {task_id}")
            resolve_assignee.delay(task_id)
        elif status == "NEEDS_REVIEW":
            logger.info(f"Task needs review: {task_id}")
    
    async def handle_task_assigned(self, event: Dict[str, Any]):
        """Handle task assigned - trigger sync to integrations."""
        task_id = event.get("task_id")
        
        logger.info(f"Task assigned, syncing to integrations: {task_id}")
        
        sync_task_to_integrations.delay(task_id)
    
    async def handle_sync_requested(self, event: Dict[str, Any]):
        """Handle sync requested - retry sync."""
        task_id = event.get("task_id")
        integration_id = event.get("integration_id")
        retry_count = event.get("retry_count", 0)
        
        logger.info(f"Sync requested for task {task_id} (retry {retry_count})")
        
        # This would call the sync function directly
        # For now, use Celery
        retry_failed_sync.delay(task_id, integration_id)
    
    async def handle_integration_webhook(self, event: Dict[str, Any]):
        """Handle integration webhook — update task status from external system."""
        provider = event.get("provider")
        payload = event.get("payload")
        integration_id = event.get("integration_id")
        
        logger.info(f"Webhook received from {provider} for integration {integration_id}")
        
        try:
            from app.integrations.factory import IntegrationAdapterFactory
            from app.db.prisma import get_prisma
            
            adapter = IntegrationAdapterFactory.get_adapter(provider)
            
            # Normalize webhook into a canonical event
            normalized = adapter.normalize_webhook(payload)
            
            if not normalized.external_id:
                logger.warning(f"Webhook from {provider} has no external_id, skipping")
                return
            
            db = await get_prisma()
            
            # Find the task by external ID
            task = await db.task.find_first(
                where={
                    "externalId": normalized.external_id,
                    "integrationId": integration_id,
                },
            )
            
            if not task:
                logger.warning(f"No task found for external_id={normalized.external_id}")
                return
            
            # Map external status to internal status
            status_map = {
                "done": "COMPLETED",
                "in_progress": "SYNCED",
                "todo": "ASSIGNED",
                "cancelled": "DISMISSED",
            }
            
            new_status = status_map.get(normalized.status)
            if new_status and new_status != task.status:
                await db.task.update(
                    where={"id": task.id},
                    data={
                        "status": new_status,
                        "lastSyncedAt": normalized.changed_at,
                    },
                )
                
                await db.taskauditlog.create(
                    data={
                        "taskId": task.id,
                        "previousStatus": task.status,
                        "newStatus": new_status,
                        "changedBy": f"webhook_{provider}",
                        "reason": f"External status update from {provider}: {normalized.status}",
                    }
                )
                
                logger.info(f"Updated task {task.id} status to {new_status} from {provider} webhook")
            
        except Exception as e:
            logger.error(f"Failed to process webhook from {provider}: {e}")


# Global manager
kafka_consumer_manager = KafkaConsumerManager()


async def send_integration_sync(tenant_id: str, integration_id: str) -> None:
    """
    Queue sync of all synced tasks for an integration.

    Dispatches straight to Celery: Kafka is no longer an orchestration hop
    (the API previously ran six consumers that duplicated Celery's work and
    multiplied across uvicorn workers). The KafkaEventBus remains available
    as a pure event publisher (HITL/webhook notifications).
    """
    from app.db.prisma import get_prisma

    db = await get_prisma()
    tasks = await db.task.find_many(
        where={"integrationId": integration_id, "syncStatus": {"in": ["SYNCED", "SYNC_FAILED"]}},
    )

    logger.info(
        f"Queueing sync for {len(tasks)} task(s) on integration {integration_id}"
    )
    for task in tasks:
        retry_failed_sync.delay(task.id, integration_id)


# Startup/shutdown handlers
async def startup_kafka():
    """Start Kafka consumers on application startup."""
    await kafka_consumer_manager.start_all()


async def shutdown_kafka():
    """Stop Kafka consumers on application shutdown."""
    await kafka_consumer_manager.stop_all()