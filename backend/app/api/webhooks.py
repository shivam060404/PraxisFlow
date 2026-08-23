"""
Webhook Handler for PraxisFlow
Handles incoming webhooks from integrations (Jira, Asana, Linear, Slack, etc.)
"""

import hmac
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, HTTPException, Header, Depends, status
from pydantic import BaseModel

from app.db.prisma import get_prisma
from app.integrations.factory import IntegrationAdapterFactory
from app.security import require_permission, Permission
from app.agents.graph_runner import (
    resume_extraction_pipeline_wrapper,
    check_pipeline_status,
    create_hitl_approval_feedback,
    create_hitl_modification_feedback,
)
from app.agents.schemas import HITLPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@dataclass
class WebhookVerificationResult:
    valid: bool
    error: Optional[str] = None


class WebhookVerifier(ABC):
    """Abstract base for webhook signature verification."""
    
    @abstractmethod
    async def verify(self, request: Request, secret: str) -> WebhookVerificationResult:
        pass


class HMACVerifier(WebhookVerifier):
    """HMAC-SHA256 verification (Jira, GitHub, Linear, etc.)."""
    
    def __init__(self, header_name: str, algorithm: str = "sha256"):
        self.header_name = header_name
        self.algorithm = algorithm
    
    async def verify(self, request: Request, secret: str) -> WebhookVerificationResult:
        signature = request.headers.get(self.header_name)
        if not signature:
            return WebhookVerificationResult(valid=False, error=f"Missing {self.header_name} header")
        
        body = await request.body()
        expected = hmac.new(
            secret.encode(),
            body,
            getattr(hashlib, self.algorithm)
        ).hexdigest()
        
        # Handle different signature formats
        if signature.startswith(f"{self.algorithm}="):
            signature = signature[len(f"{self.algorithm}="):]
        elif signature.startswith("sha256="):
            signature = signature[7:]
        
        if not hmac.compare_digest(signature, expected):
            return WebhookVerificationResult(valid=False, error="Invalid signature")
        
        return WebhookVerificationResult(valid=True)


class SlackVerifier(WebhookVerifier):
    """Slack request verification."""
    
    async def verify(self, request: Request, secret: str) -> WebhookVerificationResult:
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        signature = request.headers.get("X-Slack-Signature")
        
        if not timestamp or not signature:
            return WebhookVerificationResult(valid=False, error="Missing Slack headers")
        
        # Check timestamp (prevent replay attacks)
        if abs(int(timestamp) - int(datetime.utcnow().timestamp())) > 300:
            return WebhookVerificationResult(valid=False, error="Request timestamp too old")
        
        body = await request.body()
        sig_basestring = f"v0:{timestamp}:{body.decode()}"
        expected = "v0=" + hmac.new(
            secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected):
            return WebhookVerificationResult(valid=False, error="Invalid Slack signature")
        
        return WebhookVerificationResult(valid=True)


class AsanaVerifier(WebhookVerifier):
    """Asana webhook verification."""
    
    async def verify(self, request: Request, secret: str) -> WebhookVerificationResult:
        # Asana uses X-Hook-Secret for initial handshake, then HMAC for events
        hook_secret = request.headers.get("X-Hook-Secret")
        if hook_secret:
            # This is a handshake - verify secret matches
            if hook_secret != secret:
                return WebhookVerificationResult(valid=False, error="Invalid hook secret")
            return WebhookVerificationResult(valid=True)
        
        # For actual events, verify HMAC
        signature = request.headers.get("X-Asana-Signature")
        if not signature:
            return WebhookVerificationResult(valid=False, error="Missing Asana signature")
        
        body = await request.body()
        expected = hmac.new(
            secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected):
            return WebhookVerificationResult(valid=False, error="Invalid Asana signature")
        
        return WebhookVerificationResult(valid=True)


# Verifier registry
VERIFIERS = {
    "jira": HMACVerifier("X-Hub-Signature-256"),
    "github": HMACVerifier("X-Hub-Signature-256"),
    "gitlab": HMACVerifier("X-Gitlab-Token"),  # Uses token, not HMAC
    "linear": HMACVerifier("Linear-Signature"),
    "slack": SlackVerifier(),
    "asana": AsanaVerifier(),
    "teams": HMACVerifier("Authorization"),  # Teams uses different auth
}


# ─── Webhook Endpoints ───

# Providers backed by a Prisma enum + registered adapter
SUPPORTED_PROVIDERS = {"jira", "asana", "linear", "slack", "teams"}


async def receive_webhook(
    provider: str,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
):
    """
    Generic webhook receiver for all integrations.

    Webhooks carry no tenant context, so we look up every ACTIVE integration
    for this provider across tenants and verify the signature against each
    stored webhook secret until one validates (standard multi-tenant pattern).
    """
    provider_l = provider.lower()
    if provider_l not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unsupported provider: {provider}")

    verifier = VERIFIERS.get(provider_l)
    if not verifier:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    db = await get_prisma()
    integrations = await db.integration.find_many(
        where={"provider": provider_l, "status": "ACTIVE"}
    )

    if not integrations:
        raise HTTPException(status_code=404, detail="Integration not configured")

    # Verify signature against each candidate tenant's secret
    integration = None
    verification_error = None
    for candidate in integrations:
        secret = candidate.webhookSecret or x_webhook_secret
        if not secret:
            continue
        result = await verifier.verify(request, secret)
        if result.valid:
            integration = candidate
            break
        verification_error = result.error

    if integration is None:
        logger.warning(
            f"Webhook verification failed for {provider}: {verification_error}"
        )
        raise HTTPException(
            status_code=401,
            detail=verification_error or "Webhook secret not configured",
        )

    # Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Dispatch to integration handler
    try:
        adapter = IntegrationAdapterFactory.get_adapter(provider_l)
        event = adapter.normalize_webhook(payload)

        await _process_webhook_event(provider_l, event, integration)

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed for {provider}: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def _process_webhook_event(provider: str, event, integration):
    """Process a normalized webhook event (external status change)."""
    db = await get_prisma()

    if not event.external_id:
        logger.info(f"{provider} webhook carried no external_id; ignoring")
        return

    task = await db.task.find_first(
        where={
            "externalId": event.external_id,
            "integrationId": integration.id,
        }
    )

    if not task:
        logger.info(f"No local task for external_id={event.external_id} ({provider})")
        return

    new_status = _map_external_status(provider, event.status or "")
    if new_status == task.status:
        return

    await db.task.update(
        where={"id": task.id},
        data={
            "status": new_status,
            "syncStatus": "SYNCED",
        },
    )

    await db.taskauditlog.create(
        data={
            "taskId": task.id,
            "previousStatus": task.status,
            "newStatus": new_status,
            "changedBy": f"webhook_{provider}",
            "reason": f"Status update from {provider}: {event.status}",
            "metadata": {
                "provider": provider,
                "external_url": event.external_url,
                "changed_at": str(event.changed_at),
            },
        }
    )

    logger.info(
        f"Task {task.id} moved {task.status} -> {new_status} via {provider} webhook"
    )


def _map_external_status(provider: str, status: str) -> str:
    """Map external status to PraxisFlow status."""
    mappings = {
        "jira": {
            "To Do": "EXTRACTED",
            "In Progress": "ASSIGNED",
            "In Review": "SYNCED",
            "Done": "COMPLETED",
        },
        "asana": {
            "New": "EXTRACTED",
            "In Progress": "ASSIGNED",
            "Completed": "COMPLETED",
        },
        "linear": {
            "Backlog": "EXTRACTED",
            "Started": "ASSIGNED",
            "In Progress": "ASSIGNED",
            "Done": "COMPLETED",
        },
    }
    return mappings.get(provider.lower(), {}).get(status, "SYNCED")


# ─── Specific Webhook Endpoints ───

@router.post("/jira")
async def jira_webhook(request: Request):
    """Jira-specific webhook endpoint."""
    return await receive_webhook("jira", request)


@router.post("/asana")
async def asana_webhook(request: Request):
    """Asana-specific webhook endpoint."""
    return await receive_webhook("asana", request)


@router.post("/linear")
async def linear_webhook(request: Request):
    """Linear-specific webhook endpoint."""
    return await receive_webhook("linear", request)


@router.post("/github")
async def github_webhook(request: Request):
    """GitHub-specific webhook endpoint."""
    return await receive_webhook("github", request)


@router.post("/slack")
async def slack_webhook(request: Request):
    """Slack-specific webhook endpoint (slash commands, events)."""
    return await receive_webhook("slack", request)


@router.post("/teams")
async def teams_webhook(request: Request):
    """Microsoft Teams webhook endpoint."""
    return await receive_webhook("teams", request)


# ─── Webhook Management ───

class WebhookRegistration(BaseModel):
    provider: str
    url: str
    events: List[str]
    secret: Optional[str] = None


@router.post("/register", dependencies=[Depends(require_permission(Permission.INTEGRATION_CREATE))])
async def register_webhook(
    registration: WebhookRegistration,
    current_user = Depends(require_permission(Permission.INTEGRATION_CREATE)),
):
    """Register a new webhook with an external provider.

    Provider-side webhook registration APIs are not implemented in the
    adapters yet; this returns an explicit 501 instead of crashing.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            f"{registration.provider} adapter does not implement server-side "
            "webhook registration yet. Configure the webhook directly in the "
            "provider console pointing at /api/v1/webhooks/{provider}."
        ),
    )


@router.delete("/{provider}", dependencies=[Depends(require_permission(Permission.INTEGRATION_DELETE))])
async def unregister_webhook(
    provider: str,
    current_user = Depends(require_permission(Permission.INTEGRATION_DELETE)),
):
    """Unregister a webhook from a provider (not implemented in adapters yet)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{provider} adapter does not implement webhook deregistration yet.",
    )


@router.get("/{provider}/test", dependencies=[Depends(require_permission(Permission.INTEGRATION_READ))])
async def test_webhook(
    provider: str,
    current_user = Depends(require_permission(Permission.INTEGRATION_READ)),
):
    """Send a test webhook payload from the provider (not implemented yet)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{provider} adapter does not implement test webhook delivery yet.",
    )


# ─── HITL (Human-in-the-Loop) Webhook Endpoints ───

class HITLTaskFeedback(BaseModel):
    """Feedback for a single task in HITL review."""
    task_id: str  # Task title or identifier
    action: Literal["APPROVE", "REJECT", "MODIFY"]
    modifications: Optional[Dict[str, Any]] = None


class HITLResumeRequest(BaseModel):
    """Request to resume a paused pipeline with human feedback."""
    meeting_id: str
    tasks: List[HITLTaskFeedback]  # List of task feedbacks
    reviewer_id: Optional[str] = None
    comment: Optional[str] = None


class HITLStatusResponse(BaseModel):
    """Response for pipeline status check."""
    status: str
    meeting_id: str
    progress: float
    interrupt_node: Optional[str] = None
    interrupt_reason: Optional[str] = None
    interrupt_payload: Optional[Dict[str, Any]] = None
    tasks_created: Optional[int] = None
    errors: Optional[List[str]] = None


@router.post("/hitl/resume", response_model=Dict[str, Any])
async def hitl_resume_pipeline(
    request: HITLResumeRequest,
    current_user = Depends(require_permission(Permission.TASK_UPDATE)),
):
    """
    Resume a paused extraction pipeline after human review.
    
    This endpoint is called by the frontend when a human approves/rejects/modifies
    tasks that were flagged for review during the verification step.
    """
    # Build human feedback dict for multiple tasks
    feedback = {
        "tasks": [],
        "reviewer_id": request.reviewer_id or current_user.id,
        "comment": request.comment,
    }
    
    for task_feedback in request.tasks:
        feedback["tasks"].append({
            "task_id": task_feedback.task_id,
            "action": task_feedback.action,
            "modifications": task_feedback.modifications,
        })
    
    try:
        final_state = await resume_extraction_pipeline_wrapper(
            meeting_id=request.meeting_id,
            human_feedback=feedback,
        )
        
        return {
            "status": "resumed",
            "meeting_id": request.meeting_id,
            "tasks_finalized": len(final_state.final_tasks) if final_state.final_tasks else 0,
            "errors": final_state.errors,
        }
        
    except Exception as e:
        logger.error(f"HITL resume failed for meeting {request.meeting_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume pipeline: {str(e)}")


@router.get("/hitl/status/{meeting_id}", response_model=HITLStatusResponse)
async def hitl_pipeline_status(
    meeting_id: str,
    current_user = Depends(require_permission(Permission.TASK_READ)),
):
    """
    Check the status of an extraction pipeline, including HITL interrupt state.
    
    Returns whether the pipeline is running, completed, failed, or interrupted
    waiting for human review.
    """
    status = await check_pipeline_status(meeting_id)
    return HITLStatusResponse(**status)


@router.get("/hitl/pending", response_model=List[HITLStatusResponse])
async def hitl_pending_reviews(
    tenant_id: str,
    current_user = Depends(require_permission(Permission.TASK_READ)),
):
    """
    List all pipelines currently waiting for human review (interrupted).
    
    Useful for dashboard showing pending HITL tasks.
    """
    # This would require a more complex query - for now return empty
    # In production, you'd track interrupted pipelines in a separate table
    return []


# ─── Webhook Event Types for HITL ───

HITL_EVENT_TYPES = [
    "pipeline.interrupted",
    "pipeline.resumed",
    "pipeline.completed",
    "pipeline.failed",
]


async def emit_hitl_event(
    event_type: str,
    meeting_id: str,
    tenant_id: str,
    payload: Dict[str, Any],
):
    """Emit HITL event to Kafka for real-time UI updates."""
    from app.services.kafka_events import kafka_event_publisher
    
    event = {
        "type": event_type,
        "meeting_id": meeting_id,
        "tenant_id": tenant_id,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    await kafka_event_publisher.publish("hitl-events", event)


# ─── Generic Catch-all Route (must be registered LAST) ───

@router.post("/{provider}")
async def receive_webhook_endpoint(
    provider: str,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
):
    """Generic webhook receiver — registered after all concrete webhook paths."""
    return await receive_webhook(provider, request, x_webhook_secret)
