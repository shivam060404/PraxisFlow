import asyncio
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaError

from app.core.config import settings

logger = None  # Will be initialized

class KafkaEventBus:
    """Kafka event bus for async event-driven architecture."""
    
    def __init__(self):
        self.producer: Optional[AIOKafkaProducer] = None
        self.consumers: List[AIOKafkaConsumer] = []
        self._initialized = False
    
    async def initialize(self):
        """Initialize Kafka producer."""
        if self._initialized:
            return
        
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            compression_type="gzip",
            acks="all",
            max_batch_size=16384,
            linger_ms=10,
        )
        
        await self.producer.start()
        self._initialized = True
        logger.info("Kafka producer initialized")
    
    async def close(self):
        """Close Kafka connections."""
        if self.producer:
            await self.producer.stop()
        
        for consumer in self.consumers:
            await consumer.stop()
        
        self._initialized = False
        logger.info("Kafka connections closed")
    
    async def send(self, topic: str, event: Dict[str, Any], key: Optional[str] = None, delay_ms: int = 0):
        """Send event to Kafka topic."""
        if not self._initialized:
            await self.initialize()
        
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        
        # Use tenant_id as key for partitioning
        partition_key = key or event.get("tenant_id")
        
        try:
            await self.producer.send_and_wait(
                topic,
                value=event,
                key=partition_key,
            )
            logger.debug(f"Event sent to {topic}: {event.get('event_type', 'unknown')}")
        except KafkaError as e:
            logger.error(f"Failed to send event to {topic}: {e}")
            raise
    
    async def send_batch(self, topic: str, events: List[Dict[str, Any]]):
        """Send multiple events as a batch."""
        if not self._initialized:
            await self.initialize()
        
        for event in events:
            partition_key = event.get("tenant_id")
            await self.producer.send(
                topic,
                value=event,
                key=partition_key,
            )
        
        await self.producer.flush()
    
    def create_consumer(
        self,
        topics: List[str],
        group_id: str,
        handler: callable,
        **kwargs
    ) -> AIOKafkaConsumer:
        """Create a Kafka consumer with handler."""
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            **kwargs
        )
        
        self.consumers.append(consumer)
        return consumer


# Event topics
class Topics:
    MEETING_UPLOADED = "meeting.uploaded"
    TRANSCRIPT_COMPLETED = "transcript.completed"
    TASKS_EXTRACTED = "tasks.extracted"
    TASK_VERIFIED = "task.verified"
    TASK_ASSIGNED = "task.assigned"
    TASK_SYNC_REQUESTED = "task.sync_requested"
    TASK_COMPLETED = "task.completed"
    INTEGRATION_WEBHOOK_RECEIVED = "integration.webhook.received"
    MEETING_PROCESSING_FAILED = "meeting.processing_failed"


# Event schemas
class EventBuilder:
    """Build standardized events."""
    
    @staticmethod
    def meeting_uploaded(meeting_id: str, tenant_id: str, audio_url: str) -> Dict[str, Any]:
        return {
            "event_type": "meeting.uploaded",
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "audio_url": audio_url,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def transcript_completed(meeting_id: str, transcript_id: str, tenant_id: str, word_count: int) -> Dict[str, Any]:
        return {
            "event_type": "transcript.completed",
            "meeting_id": meeting_id,
            "transcript_id": transcript_id,
            "tenant_id": tenant_id,
            "word_count": word_count,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def tasks_extracted(meeting_id: str, tenant_id: str, task_ids: List[str], task_count: int) -> Dict[str, Any]:
        return {
            "event_type": "tasks.extracted",
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "task_ids": task_ids,
            "task_count": task_count,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def task_verified(task_id: str, tenant_id: str, status: str, reasoning: str = "") -> Dict[str, Any]:
        return {
            "event_type": "task.verified",
            "task_id": task_id,
            "tenant_id": tenant_id,
            "verification_status": status,
            "reasoning": reasoning,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def task_assigned(task_id: str, tenant_id: str, assignee_id: str, resolved_by: str) -> Dict[str, Any]:
        return {
            "event_type": "task.assigned",
            "task_id": task_id,
            "tenant_id": tenant_id,
            "assignee_id": assignee_id,
            "resolved_by": resolved_by,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def task_sync_requested(task_id: str, tenant_id: str, integration_id: str, retry_count: int = 0) -> Dict[str, Any]:
        return {
            "event_type": "task.sync_requested",
            "task_id": task_id,
            "tenant_id": tenant_id,
            "integration_id": integration_id,
            "retry_count": retry_count,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def integration_webhook(provider: str, payload: Dict[str, Any], integration_id: str) -> Dict[str, Any]:
        return {
            "event_type": "integration.webhook.received",
            "provider": provider,
            "payload": payload,
            "integration_id": integration_id,
            "timestamp": datetime.utcnow().isoformat(),
        }


# Global instance
kafka_event_bus = KafkaEventBus()