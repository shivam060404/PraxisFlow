"""
Webhook Handler for PraxisFlow
Handles incoming webhooks from integrations (Jira, Asana, Linear, Slack, etc.)
"""

import hmac
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, Header, Depends
from pydantic import BaseModel

from app.db.prisma import get_prisma
from app.integrations.factory import IntegrationFactory
from app.security import require_permission, Permission
from app.schemas import WebhookEvent

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

@router.post("/{provider}")
async def receive_webhook(
    provider: str,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
):
    """
    Generic webhook receiver for all integrations.
    Verifies signature and dispatches to appropriate handler.
    """
    # Get integration config
    db = await get_prisma()
    integration = await db.integration.find_unique(
        where={"tenantId_provider": {"tenantId": "TODO_GET_TENANT", "provider": provider.upper()}}
    )
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not configured")
    
    # Verify signature
    verifier = VERIFIERS.get(provider.lower())
    if not verifier:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    
    secret = integration.webhookSecret or x_webhook_secret
    if not secret:
        raise HTTPException(status_code=400, detail="Webhook secret not configured")
    
    result = await verifier.verify(request, secret)
    if not result.valid:
        logger.warning(f"Webhook verification failed for {provider}: {result.error}")
        raise HTTPException(status_code=401, detail=result.error)
    
    # Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Dispatch to integration handler
    try:
        adapter = IntegrationFactory.create(provider, integration.config)
        event = await adapter.normalize_webhook(payload)
        
        # Process based on event type
        await _process_webhook_event(provider, event, integration)
        
        return {"status": "ok"}
    
    except Exception as e:
        logger.error(f"Webhook processing failed for {provider}: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def _process_webhook_event(provider: str, event: WebhookEvent, integration):
    """Process webhook event based on type."""
    db = await get_prisma()
    
    if event.type == "task.updated" or event.type == "issue.updated":
        # Find corresponding task
        task = await db.task.find_unique(
            where={"externalId_integrationId": {"externalId": event.resource_id, "integrationId": integration.id}}
        )
        
        if task:
            # Update task from external changes
            updates = {}
            if event.changes.get("status"):
                updates["status"] = _map_external_status(provider, event.changes["status"])
            if event.changes.get("assignee"):
                updates["assigneeId"] = await _resolve_assignee(event.changes["assignee"], integration.tenantId)
            if event.changes.get("dueDate"):
                updates["deadlineDate"] = event.changes["dueDate"]
            
            if updates:
                await db.task.update(where={"id": task.id}, data=updates)
                
                # Create audit log
                await db.taskauditlog.create(
                    data={
                        "taskId": task.id,
                        "previousStatus": task.status,
                        "newStatus": updates.get("status", task.status),
                        "changedBy": "webhook",
                        "reason": f"Updated via {provider} webhook",
                        "metadata": {"provider": provider, "event": event.dict()},
                    }
                )
    
    elif event.type == "task.created":
        # Could auto-create task in PraxisFlow if configured
        pass
    
    elif event.type == "task.deleted":
        # Handle external deletion
        task = await db.task.find_unique(
            where={"externalId_integrationId": {"externalId": event.resource_id, "integrationId": integration.id}}
        )
        if task:
            await db.task.update(
                where={"id": task.id},
                data={"syncStatus": "CONFLICT", "status": "DISMISSED"}
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


async def _resolve_assignee(external_id: str, tenant_id: str) -> Optional[str]:
    """Resolve external assignee to internal user."""
    db = await get_prisma()
    user = await db.user.find_first(
        where={"tenantId": tenant_id, "attributes": {"path": "$.external_ids", "array_contains": external_id}}
    )
    return user.id if user else None


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
    """Register a new webhook with an external provider."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"tenantId_provider": {"tenantId": current_user.tenant_id, "provider": registration.provider.upper()}}
    )
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Register with provider
    adapter = IntegrationFactory.create(registration.provider, integration.config)
    
    try:
        webhook_id = await adapter.register_webhook(
            url=registration.url,
            events=registration.events,
            secret=registration.secret,
        )
        
        # Update integration with webhook ID
        await db.integration.update(
            where={"id": integration.id},
            data={"webhookId": webhook_id, "webhookUrl": registration.url}
        )
        
        return {"webhook_id": webhook_id, "status": "registered"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register webhook: {e}")


@router.delete("/{provider}", dependencies=[Depends(require_permission(Permission.INTEGRATION_DELETE))])
async def unregister_webhook(
    provider: str,
    current_user = Depends(require_permission(Permission.INTEGRATION_DELETE)),
):
    """Unregister webhook from provider."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"tenantId_provider": {"tenantId": current_user.tenant_id, "provider": provider.upper()}}
    )
    
    if not integration or not integration.webhookId:
        raise HTTPException(status_code=404, detail="Webhook not registered")
    
    adapter = IntegrationFactory.create(provider, integration.config)
    
    try:
        await adapter.unregister_webhook(integration.webhookId)
        
        await db.integration.update(
            where={"id": integration.id},
            data={"webhookId": None, "webhookUrl": None}
        )
        
        return {"status": "unregistered"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unregister webhook: {e}")


@router.get("/{provider}/test", dependencies=[Depends(require_permission(Permission.INTEGRATION_READ))])
async def test_webhook(
    provider: str,
    current_user = Depends(require_permission(Permission.INTEGRATION_READ)),
):
    """Send a test webhook to verify configuration."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"tenantId_provider": {"tenantId": current_user.tenant_id, "provider": provider.upper()}}
    )
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    adapter = IntegrationFactory.create(provider, integration.config)
    
    try:
        result = await adapter.send_test_webhook()
        return {"status": "sent", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Test webhook failed: {e}")