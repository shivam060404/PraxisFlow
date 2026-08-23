from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.db.prisma import get_db
from app.schemas import (
    Integration, IntegrationCreate, IntegrationUpdate, IntegrationProvider,
    PaginatedResponse, to_prisma_data
)
from app.security import get_current_subject, Subject
from app.integrations.factory import IntegrationAdapterFactory

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.post("", response_model=Integration, status_code=status.HTTP_201_CREATED)
async def create_integration(
    integration_data: IntegrationCreate,
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Create a new integration."""
    # Check if integration already exists for this tenant/provider
    existing = await db.integration.find_first(
        where={
            "tenantId": subject.tenant_id,
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
            "tenantId": subject.tenant_id,
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
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """List all integrations for the current tenant."""
    total = await db.integration.count()
    integrations = await db.integration.find_many(
        where={"tenantId": subject.tenant_id},
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
    subject: Subject = Depends(get_current_subject),
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
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Update an integration."""
    integration = await db.integration.find_first(
        where={"id": str(integration_id), "tenantId": subject.tenant_id}
    )
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
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Delete an integration."""
    integration = await db.integration.find_first(
        where={"id": str(integration_id), "tenantId": subject.tenant_id}
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    
    await db.integration.delete(where={"id": str(integration_id)})


@router.post("/{integration_id}/test", response_model=dict)
async def test_integration(
    integration_id: UUID,
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Test an integration connection."""
    integration = await db.integration.find_first(
        where={"id": str(integration_id), "tenantId": subject.tenant_id}
    )
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
# All provider webhooks are handled by the canonical, HMAC-verified receiver
# in app/api/webhooks.py (multi-tenant secret matching, normalized events,
# audit logging). These thin aliases keep the historical /integrations/webhooks
# URLs working without duplicating security-sensitive logic.

async def _delegate_webhook(provider: str, request: Request):
    from app.api.webhooks import receive_webhook

    return await receive_webhook(provider, request, request.headers.get("X-Webhook-Secret"))


@router.post("/webhooks/jira")
async def jira_webhook(request: Request):
    """Jira webhook (delegates to canonical verified receiver)."""
    return await _delegate_webhook("jira", request)


@router.post("/webhooks/asana")
async def asana_webhook(request: Request):
    """Asana webhook (delegates to canonical verified receiver)."""
    return await _delegate_webhook("asana", request)


@router.post("/webhooks/linear")
async def linear_webhook(request: Request):
    """Linear webhook (delegates to canonical verified receiver)."""
    return await _delegate_webhook("linear", request)


@router.post("/webhooks/slack")
async def slack_webhook(request: Request):
    """Slack webhook (delegates to canonical verified receiver)."""
    return await _delegate_webhook("slack", request)
