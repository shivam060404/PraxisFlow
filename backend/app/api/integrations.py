from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.db.prisma import get_db
from app.schemas import (
    Integration, IntegrationCreate, IntegrationUpdate, IntegrationProvider,
    PaginatedResponse, to_prisma_data
)
from app.integrations.factory import IntegrationAdapterFactory

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.post("", response_model=Integration, status_code=status.HTTP_201_CREATED)
async def create_integration(
    integration_data: IntegrationCreate,
    db=Depends(get_db),
):
    """Create a new integration."""
    # Check if integration already exists for this tenant/provider
    existing = await db.integration.find_first(
        where={
            "tenantId": str(integration_data.tenant_id),
            "provider": integration_data.provider,
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Integration for {integration_data.provider} already exists",
        )
    
    integration = await db.integration.create(
        data={
            "tenantId": str(integration_data.tenant_id),
            "provider": integration_data.provider,
            "displayName": integration_data.display_name,
            "config": integration_data.config,
            "webhookSecret": integration_data.webhook_secret,
            "status": "ACTIVE",
        }
    )
    
    return integration


@router.get("", response_model=PaginatedResponse)
async def list_integrations(
    page: int = 1,
    page_size: int = 20,
    db=Depends(get_db),
):
    """List all integrations for the current tenant."""
    total = await db.integration.count()
    integrations = await db.integration.find_many(
        skip=(page - 1) * page_size,
        take=page_size,
        order={"createdAt": "desc"},
    )
    
    return PaginatedResponse(
        items=integrations,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{integration_id}", response_model=Integration)
async def get_integration(
    integration_id: UUID,
    db=Depends(get_db),
):
    """Get a single integration."""
    integration = await db.integration.find_unique(
        where={"id": str(integration_id)},
    )
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    
    return integration


@router.patch("/{integration_id}", response_model=Integration)
async def update_integration(
    integration_id: UUID,
    integration_data: IntegrationUpdate,
    db=Depends(get_db),
):
    """Update an integration."""
    integration = await db.integration.find_unique(where={"id": str(integration_id)})
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    
    updated = await db.integration.update(
        where={"id": str(integration_id)},
        data=to_prisma_data(integration_data),
    )
    
    return updated


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: UUID,
    db=Depends(get_db),
):
    """Delete an integration."""
    integration = await db.integration.find_unique(where={"id": str(integration_id)})
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    
    await db.integration.delete(where={"id": str(integration_id)})


@router.post("/{integration_id}/test", response_model=dict)
async def test_integration(
    integration_id: UUID,
    db=Depends(get_db),
):
    """Test an integration connection."""
    integration = await db.integration.find_unique(where={"id": str(integration_id)})
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    
    try:
        adapter = IntegrationAdapterFactory.get_adapter(integration.provider)
        result = await adapter.test_connection(integration)
        return {"success": True, "message": "Connection successful", "details": result}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ─── Webhook Handlers ───

@router.post("/webhooks/jira")
async def jira_webhook(
    request: Request,
    db=Depends(get_db),
):
    """Handle Jira webhooks."""
    payload = await request.json()
    
    # Find integration by webhook secret
    signature = request.headers.get("X-Hub-Signature-256", "")
    integration = await db.integration.find_first(
        where={"provider": "jira", "webhookSecret": signature}
    )
    
    if not integration:
        # Try to find by other means
        integration = await db.integration.find_first(
            where={"provider": "jira", "status": "ACTIVE"}
        )
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active Jira integration found",
        )
    
    # Process webhook
    from app.integrations.jira import JiraAdapter
    adapter = JiraAdapter()
    normalized = adapter.normalize_webhook(payload)
    
    # Find our internal task
    task = await db.task.find_first(
        where={
            "externalId": normalized.external_id,
            "integrationId": integration.id,
        }
    )
    
    if not task:
        return {"status": "ignored", "reason": "Task not found in our system"}
    
    # Update task status based on webhook
    if normalized.status == "done" and task.status != "COMPLETED":
        await db.task.update(
            where={"id": task.id},
            data={
                "status": "COMPLETED",
                "updatedAt": datetime.utcnow(),
            }
        )
        
        # Audit log
        await db.taskauditlog.create(
            data={
                "taskId": task.id,
                "previousStatus": task.status,
                "newStatus": "COMPLETED",
                "changedBy": f"integration:jira",
                "reason": f"Marked done in Jira",
            }
        )
    
    return {"status": "processed", "task_id": task.id}


@router.post("/webhooks/asana")
async def asana_webhook(
    request: Request,
    db=Depends(get_db),
):
    """Handle Asana webhooks."""
    payload = await request.json()
    
    # Asana sends events array
    events = payload.get("events", [])
    
    for event in events:
        # Process each event
        pass
    
    return {"status": "received", "events": len(events)}


@router.post("/webhooks/linear")
async def linear_webhook(
    request: Request,
    db=Depends(get_db),
):
    """Handle Linear webhooks."""
    payload = await request.json()
    
    # Process Linear webhook
    return {"status": "received"}


@router.post("/webhooks/slack")
async def slack_webhook(
    request: Request,
    db=Depends(get_db),
):
    """Handle Slack webhooks/events."""
    payload = await request.json()
    
    # Handle Slack events (reactions, messages, etc.)
    return {"status": "received"}