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

from app.db.prisma import get_prisma, get_webhook_lookup_prisma, set_request_tenant, reset_request_tenant
from app.integrations.factory import IntegrationAdapterFactory
from app.security import require_permission, Permission
from app.ai.agents.graph_runner import (
    resume_extraction_pipeline_wrapper,
    check_pipeline_status,
)

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

    lookup_db = await get_webhook_lookup_prisma()
    integrations = await lookup_db.integration.find_many(
        where={"provider": provider_l, "status": "ACTIVE"},
        select={"id": True, "tenantId": True, "provider": True, "status": True, "webhookSecret": True},
    )

    if not integrations:
        raise HTTPException(status_code=404, detail="Integration not configured")

    # Verify signature against each candidate tenant's secret
    integration = None
    verification_error = None
    for candidate in integrations:
        secret = candidate.webhookSecret
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

        tenant_token = set_request_tenant(integration.tenantId)
        try:
            await _process_webhook_event(provider_l, event, integration)
        finally:
            reset_request_tenant(tenant_token)

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
    task_id: str  # Stable review ID returned by the interrupted graph
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
    db = await get_prisma()
    tenant_id = getattr(current_user, "tenant_id", None)
    reviewer_id = getattr(current_user, "id", None)
    meeting = await db.meeting.find_first(where={"id": request.meeting_id, "tenantId": tenant_id})
    if not tenant_id or not reviewer_id or not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not request.tasks:
        raise HTTPException(status_code=422, detail="At least one pending task decision is required")
    if len({item.task_id for item in request.tasks}) != len(request.tasks):
        raise HTTPException(status_code=422, detail="Each pending task must have exactly one decision")
    review_ids = {item.task_id for item in request.tasks}
    review_rows = await db.humanreview.find_many(
        where={
            "tenantId": tenant_id,
            "meetingId": request.meeting_id,
            "reviewId": {"in": list(review_ids)},
        },
        select={"reviewId": True, "status": True, "reviewerId": True, "decisionPayload": True},
    )
    if {row.reviewId for row in review_rows} != review_ids:
        raise HTTPException(status_code=409, detail="Review set is stale or incomplete; refresh pending reviews")

    requested_decisions = {
        item.task_id: {
            "action": item.action,
            "modifications": item.modifications,
            "comment": request.comment,
        }
        for item in request.tasks
    }
    final_status = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "MODIFY": "MODIFIED"}
    if all(
        row.status == final_status[requested_decisions[row.reviewId]["action"]]
        and row.reviewerId == reviewer_id
        and row.decisionPayload == requested_decisions[row.reviewId]
        for row in review_rows
    ):
        return {
            "status": "already_completed",
            "meeting_id": request.meeting_id,
            "tasks_finalized": len(review_rows),
            "errors": [],
        }

    if any(row.status == "IN_REVIEW" and row.reviewerId != reviewer_id for row in review_rows):
        raise HTTPException(status_code=409, detail="Another reviewer is processing this decision")
    if any(row.status not in {"PENDING", "IN_REVIEW"} for row in review_rows):
        raise HTTPException(status_code=409, detail="Review set has already been finalized")

    # Compare-and-set claims the complete review set so concurrent submissions
    # cannot resume the same LangGraph thread at the same time. A reviewer may
    # retry their own IN_REVIEW set after a transient failure.
    pending_count = sum(row.status == "PENDING" for row in review_rows)
    if pending_count:
        claimed = await db.humanreview.update_many(
            where={
                "tenantId": tenant_id,
                "meetingId": request.meeting_id,
                "reviewId": {"in": list(review_ids)},
                "status": "PENDING",
            },
            data={"status": "IN_REVIEW", "reviewerId": reviewer_id},
        )
        if claimed.count != pending_count:
            raise HTTPException(status_code=409, detail="Another reviewer is processing this decision")

    # Reviewer identity is taken from the verified token, never the request.
    feedback = {
        "tasks": [],
        "reviewer_id": reviewer_id,
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
            "tasks_finalized": len(final_state.get("final_tasks", [])) if isinstance(final_state, dict) else len(final_state.final_tasks),
            "errors": final_state.get("errors", []) if isinstance(final_state, dict) else final_state.errors,
        }
        
    except Exception as e:
        try:
            pipeline_status = await check_pipeline_status(request.meeting_id)
            if pipeline_status.get("status") == "interrupted":
                await db.humanreview.update_many(
                    where={
                        "tenantId": tenant_id,
                        "meetingId": request.meeting_id,
                        "reviewId": {"in": list(review_ids)},
                        "status": "IN_REVIEW",
                        "reviewerId": reviewer_id,
                    },
                    data={"status": "PENDING", "reviewerId": None},
                )
        except Exception:
            logger.exception("Could not release or inspect failed HITL review claim")
        logger.error(f"HITL resume failed for meeting {request.meeting_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume extraction pipeline")


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
    db = await get_prisma()
    tenant_id = getattr(current_user, "tenant_id", None)
    meeting = await db.meeting.find_first(where={"id": meeting_id, "tenantId": tenant_id})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    status = await check_pipeline_status(meeting_id)
    return HITLStatusResponse(**status)


@router.get("/hitl/pending", response_model=List[HITLStatusResponse])
async def hitl_pending_reviews(
    tenant_id: Optional[str] = None,
    current_user = Depends(require_permission(Permission.TASK_READ)),
):
    """
    List all pipelines currently waiting for human review (interrupted).
    
    Useful for dashboard showing pending HITL tasks.
    """
    authenticated_tenant = getattr(current_user, "tenant_id", None)
    if not authenticated_tenant or (tenant_id and tenant_id != authenticated_tenant):
        raise HTTPException(status_code=403, detail="Tenant scope mismatch")
    db = await get_prisma()
    rows = await db.humanreview.find_many(
        where={"tenantId": authenticated_tenant, "status": {"in": ["PENDING", "IN_REVIEW"]}},
        order={"createdAt": "asc"},
    )
    grouped: Dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.meetingId, []).append(row)
    return [
        HITLStatusResponse(
            status="interrupted",
            meeting_id=meeting_id,
            progress=0.7,
            interrupt_node="human_review",
            interrupt_reason=f"{len(review_rows)} task(s) require human review",
            interrupt_payload={"tasks": [
                {
                    "task_id": row.reviewId,
                    "task_data": row.taskData,
                    "transcript_evidence": row.transcriptEvidence,
                    "interrupt_reason": row.reason,
                    "confidence_score": row.confidence,
                }
                for row in review_rows
            ]},
        )
        for meeting_id, review_rows in grouped.items()
    ]


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
