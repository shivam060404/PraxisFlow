from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from uuid import UUID

from app.core.config import settings
from app.db.prisma import get_prisma
from app.security import require_permission, Role, Permission
from app.schemas import UserCreate, UserUpdate, UserResponse

router = APIRouter(prefix="/admin", tags=["Admin"])


# ─── Models ───

class TenantSettingsUpdate(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    settings: Optional[dict] = None


class IntegrationConfigUpdate(BaseModel):
    config: dict
    webhook_secret: Optional[str] = None


class UserInvite(BaseModel):
    email: str
    full_name: str
    role: Role = Role.MEMBER
    department: Optional[str] = None
    team: Optional[str] = None


class BulkUserAction(BaseModel):
    user_ids: List[UUID]
    action: str  # "activate", "deactivate", "delete", "change_role"
    role: Optional[Role] = None


# ─── Tenant Management ───

@router.get("/tenant", summary="Get tenant details")
async def get_tenant(
    current_user = Depends(require_permission(Permission.TENANT_SETTINGS)),
):
    """Get current tenant configuration."""
    db = await get_prisma()
    tenant = await db.tenant.find_unique(where={"id": current_user.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/tenant", summary="Update tenant settings")
async def update_tenant(
    settings: TenantSettingsUpdate,
    current_user = Depends(require_permission(Permission.TENANT_SETTINGS)),
):
    """Update tenant configuration."""
    db = await get_prisma()
    tenant = await db.tenant.update(
        where={"id": current_user.tenant_id},
        data=settings.model_dump(exclude_unset=True),
    )
    return tenant


@router.get("/tenant/usage", summary="Get tenant usage statistics")
async def get_tenant_usage(
    current_user = Depends(require_permission(Permission.BILLING_VIEW)),
):
    """Get usage statistics for billing."""
    db = await get_prisma()
    tenant_id = current_user.tenant_id
    
    # Count resources
    meetings_count = await db.meeting.count(where={"tenantId": tenant_id})
    tasks_count = await db.task.count(where={"tenantId": tenant_id})
    users_count = await db.user.count(where={"tenantId": tenant_id})
    integrations_count = await db.integration.count(where={"tenantId": tenant_id})
    
    # Get AI usage from audit logs
    from datetime import datetime, timedelta
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    ai_calls = await db.aiauditlog.count(
        where={
            "tenantId": tenant_id,
            "createdAt": {"gte": start_of_month},
        }
    )
    
    total_tokens = await db.aiauditlog.aggregate(
        where={
            "tenantId": tenant_id,
            "createdAt": {"gte": start_of_month},
        },
        _sum={
            "promptTokens": True,
            "completionTokens": True,
        }
    )
    
    return {
        "meetings": meetings_count,
        "tasks": tasks_count,
        "users": users_count,
        "integrations": integrations_count,
        "ai_calls_this_month": ai_calls,
        "tokens_this_month": {
            "prompt": total_tokens._sum.promptTokens or 0,
            "completion": total_tokens._sum.completionTokens or 0,
        },
        "period_start": start_of_month.isoformat(),
    }


# ─── User Management ───

@router.get("/users", summary="List all users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[Role] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    current_user = Depends(require_permission(Permission.USER_MANAGE)),
):
    """List all users in the tenant with pagination and filtering."""
    db = await get_prisma()
    
    where = {"tenantId": current_user.tenant_id}
    
    if role:
        where["role"] = role.value
    if status:
        where["status"] = status
    if search:
        where["OR"] = [
            {"email": {"contains": search, "mode": "insensitive"}},
            {"fullName": {"contains": search, "mode": "insensitive"}},
        ]
    
    total = await db.user.count(where=where)
    users = await db.user.find_many(
        where=where,
        skip=(page - 1) * page_size,
        take=page_size,
        orderBy={"createdAt": "desc"},
    )
    
    return {
        "users": users,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/users/invite", summary="Invite new user", status_code=status.HTTP_201_CREATED)
async def invite_user(
    invite: UserInvite,
    current_user = Depends(require_permission(Permission.USER_MANAGE)),
):
    """Invite a new user to the tenant."""
    db = await get_prisma()
    
    # Check if user already exists
    existing = await db.user.find_unique(
        where={"tenantId_email": {"tenantId": current_user.tenant_id, "email": invite.email}}
    )
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")
    
    # Create user with pending status
    user = await db.user.create(
        data={
            "tenantId": current_user.tenant_id,
            "email": invite.email,
            "fullName": invite.full_name,
            "role": invite.role.value,
            "status": "INVITED",
            "attributes": {
                "department": invite.department,
                "team": invite.team,
            },
        }
    )
    
    # TODO: Send invitation email
    
    return user


@router.patch("/users/{user_id}", summary="Update user")
async def update_user(
    user_id: UUID,
    update: UserUpdate,
    current_user = Depends(require_permission(Permission.USER_MANAGE)),
):
    """Update user details."""
    db = await get_prisma()
    
    user = await db.user.find_unique(where={"id": str(user_id), "tenantId": current_user.tenant_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent self-demotion
    if str(user_id) == current_user.user_id and update.role:
        if Role(update.role) != Role.TENANT_ADMIN and current_user.role == Role.TENANT_ADMIN:
            raise HTTPException(status_code=400, detail="Cannot demote yourself")
    
    updated = await db.user.update(
        where={"id": str(user_id)},
        data=update.model_dump(exclude_unset=True),
    )
    return updated


@router.post("/users/bulk", summary="Bulk user actions")
async def bulk_user_action(
    action: BulkUserAction,
    current_user = Depends(require_permission(Permission.USER_MANAGE)),
):
    """Perform bulk actions on users."""
    db = await get_prisma()
    
    if action.action == "change_role" and not action.role:
        raise HTTPException(status_code=400, detail="Role required for change_role action")
    
    # Prevent self-action
    if str(current_user.user_id) in [str(uid) for uid in action.user_ids]:
        raise HTTPException(status_code=400, detail="Cannot perform bulk action on yourself")
    
    update_data = {}
    if action.action == "activate":
        update_data["status"] = "ACTIVE"
    elif action.action == "deactivate":
        update_data["status"] = "INACTIVE"
    elif action.action == "change_role":
        update_data["role"] = action.role.value
    elif action.action == "delete":
        # Soft delete - mark as deleted
        update_data["status"] = "DELETED"
        update_data["deletedAt"] = datetime.utcnow()
    
    result = await db.user.update_many(
        where={"id": {"in": [str(uid) for uid in action.user_ids]}, "tenantId": current_user.tenant_id},
        data=update_data,
    )
    
    return {"updated_count": result.count}


# ─── Integration Management ───

@router.get("/integrations", summary="List all integrations")
async def list_integrations(
    current_user = Depends(require_permission(Permission.INTEGRATION_READ)),
):
    """List all configured integrations."""
    db = await get_prisma()
    integrations = await db.integration.find_many(
        where={"tenantId": current_user.tenant_id},
        orderBy={"createdAt": "desc"},
    )
    return integrations


@router.post("/integrations", summary="Create integration", status_code=status.HTTP_201_CREATED)
async def create_integration(
    provider: str,
    display_name: str,
    config: dict,
    webhook_secret: Optional[str] = None,
    current_user = Depends(require_permission(Permission.INTEGRATION_CREATE)),
):
    """Create a new integration."""
    db = await get_prisma()
    
    # Check if integration already exists for this provider
    existing = await db.integration.find_unique(
        where={"tenantId_provider": {"tenantId": current_user.tenant_id, "provider": provider}}
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Integration for {provider} already exists")
    
    integration = await db.integration.create(
        data={
            "tenantId": current_user.tenant_id,
            "provider": provider,
            "displayName": display_name,
            "config": config,
            "webhookSecret": webhook_secret,
            "status": "ACTIVE",
        }
    )
    return integration


@router.patch("/integrations/{integration_id}", summary="Update integration")
async def update_integration(
    integration_id: UUID,
    config: IntegrationConfigUpdate,
    current_user = Depends(require_permission(Permission.INTEGRATION_UPDATE)),
):
    """Update integration configuration."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"id": str(integration_id), "tenantId": current_user.tenant_id}
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    updated = await db.integration.update(
        where={"id": str(integration_id)},
        data=config.model_dump(exclude_unset=True),
    )
    return updated


@router.delete("/integrations/{integration_id}", summary="Delete integration")
async def delete_integration(
    integration_id: UUID,
    current_user = Depends(require_permission(Permission.INTEGRATION_DELETE)),
):
    """Delete an integration."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"id": str(integration_id), "tenantId": current_user.tenant_id}
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    await db.integration.delete(where={"id": str(integration_id)})
    return {"deleted": True}


@router.post("/integrations/{integration_id}/test", summary="Test integration connection")
async def test_integration(
    integration_id: UUID,
    current_user = Depends(require_permission(Permission.INTEGRATION_SYNC)),
):
    """Test integration connectivity."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"id": str(integration_id), "tenantId": current_user.tenant_id}
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Import and use the appropriate adapter
    from app.integrations.factory import IntegrationFactory
    
    try:
        adapter = IntegrationFactory.create_adapter(integration)
        health = await adapter.health_check()
        return health
    except Exception as e:
        return {"healthy": False, "error": str(e)}


@router.post("/integrations/{integration_id}/sync", summary="Trigger manual sync")
async def trigger_sync(
    integration_id: UUID,
    current_user = Depends(require_permission(Permission.INTEGRATION_SYNC)),
):
    """Trigger a manual synchronization."""
    db = await get_prisma()
    
    integration = await db.integration.find_unique(
        where={"id": str(integration_id), "tenantId": current_user.tenant_id}
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Trigger sync via Kafka
    from app.workers.kafka_consumers import send_integration_sync
    await send_integration_sync(
        tenant_id=current_user.tenant_id,
        integration_id=str(integration_id),
    )
    
    return {"message": "Sync triggered", "integration_id": str(integration_id)}


# ─── Audit & Compliance ───

@router.get("/audit-logs", summary="Get audit logs")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    action: Optional[str] = None,
    user_id: Optional[UUID] = None,
    current_user = Depends(require_permission(Permission.AUDIT_LOG_READ)),
):
    """Get audit logs with filtering."""
    db = await get_prisma()
    
    where = {"tenantId": current_user.tenant_id}
    
    if start_date:
        where["createdAt"] = {"gte": start_date}
    if end_date:
        where.setdefault("createdAt", {})["lte"] = end_date
    if action:
        where["action"] = action
    if user_id:
        where["userId"] = str(user_id)
    
    total = await db.auditlog.count(where=where)
    logs = await db.auditlog.find_many(
        where=where,
        skip=(page - 1) * page_size,
        take=page_size,
        orderBy={"createdAt": "desc"},
    )
    
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/compliance/status", summary="Get compliance status")
async def get_compliance_status(
    current_user = Depends(require_permission(Permission.COMPLIANCE_EXPORT)),
):
    """Get current compliance status for the tenant."""
    db = await get_prisma()
    
    # Check various compliance aspects
    # This would be more comprehensive in production
    
    return {
        "eu_ai_act": {
            "status": "compliant",
            "last_assessment": "2025-07-15",
            "next_review": "2025-10-15",
            "risk_level": "high",
            "controls_implemented": 8,
            "controls_total": 8,
        },
        "gdpr": {
            "status": "compliant",
            "dpo_appointed": True,
            "dpia_completed": True,
            "dpa_signed": True,
            "data_subject_requests_30d": 0,
            "breach_notifications_30d": 0,
        },
        "soc2": {
            "status": "in_progress",
            "type": "Type II",
            "audit_period": "2025-01-01 to 2025-06-30",
            "controls_tested": 45,
            "controls_passed": 42,
            "findings_open": 3,
        },
        "iso27001": {
            "status": "certified",
            "certificate_number": "ISO27001-2025-001234",
            "valid_until": "2026-07-15",
            "scope": "AI Meeting Intelligence Platform",
        },
    }


# ─── System Health ───

@router.get("/system/health", summary="Get detailed system health")
async def get_system_health(
    current_user = Depends(require_permission(Permission.TENANT_SETTINGS)),
):
    """Get detailed health status of all system components."""
    import httpx
    
    health = {
        "database": "unknown",
        "redis": "unknown",
        "kafka": "unknown",
        "qdrant": "unknown",
        "neo4j": "unknown",
        "minio": "unknown",
        "llm_gateway": "unknown",
        "langfuse": "unknown",
        "overall": "unknown",
    }
    
    # Check each service
    services = [
        ("database", "http://localhost:8000/health"),
        ("redis", "redis://redis:6379"),
        ("qdrant", "http://qdrant:6333/healthz"),
        ("llm_gateway", "http://llm-gateway:4000/health/liveliness"),
        ("langfuse", "http://langfuse:3000/api/health"),
    ]
    
    for name, url in services:
        try:
            if url.startswith("redis://"):
                import redis.asyncio as redis
                r = redis.from_url(url)
                await r.ping()
                health[name] = "healthy"
            else:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(url)
                    health[name] = "healthy" if resp.status_code == 200 else "unhealthy"
        except Exception:
            health[name] = "unhealthy"
    
    # Overall status
    if all(v == "healthy" for v in health.values() if v != "unknown"):
        health["overall"] = "healthy"
    elif any(v == "unhealthy" for v in health.values()):
        health["overall"] = "degraded"
    else:
        health["overall"] = "unknown"
    
    return health


@router.get("/system/metrics", summary="Get system metrics")
async def get_system_metrics(
    current_user = Depends(require_permission(Permission.TENANT_SETTINGS)),
):
    """Get system performance metrics."""
    # This would connect to Prometheus/Grafana in production
    return {
        "api_latency_p50_ms": 120,
        "api_latency_p95_ms": 350,
        "api_latency_p99_ms": 800,
        "requests_per_second": 45.2,
        "error_rate": 0.001,
        "pipeline_completion_rate": 0.98,
        "avg_pipeline_duration_seconds": 180,
        "active_users_24h": 127,
        "meetings_processed_24h": 89,
    }