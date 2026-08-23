from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
import asyncio
from datetime import datetime, timedelta
from pydantic import BaseModel
from uuid import UUID

from app.core.config import settings
from app.db.prisma import get_prisma
from app.security import require_permission, Role, Permission
from app.schemas import UserCreate, UserUpdate, UserResponse, to_prisma_data

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
        data=to_prisma_data(settings),
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
    
    user = await db.user.find_first(where={"id": str(user_id), "tenantId": current_user.tenant_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent self-demotion
    if str(user_id) == current_user.user_id and update.role:
        if Role(update.role) != Role.TENANT_ADMIN and current_user.role == Role.TENANT_ADMIN:
            raise HTTPException(status_code=400, detail="Cannot demote yourself")
    
    updated = await db.user.update(
        where={"id": str(user_id)},
        data=to_prisma_data(update),
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
    
    integration = await db.integration.find_first(
        where={"id": str(integration_id), "tenantId": current_user.tenant_id}
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    updated = await db.integration.update(
        where={"id": str(integration_id)},
        data=to_prisma_data(config),
    )
    return updated


@router.delete("/integrations/{integration_id}", summary="Delete integration")
async def delete_integration(
    integration_id: UUID,
    current_user = Depends(require_permission(Permission.INTEGRATION_DELETE)),
):
    """Delete an integration."""
    db = await get_prisma()
    
    integration = await db.integration.find_first(
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
    
    integration = await db.integration.find_first(
        where={"id": str(integration_id), "tenantId": current_user.tenant_id}
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Import and use the appropriate adapter
    from app.integrations.factory import IntegrationAdapterFactory

    try:
        adapter, cfg = IntegrationAdapterFactory.create_adapter(integration)
        health = await adapter.test_connection(cfg)
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
    
    integration = await db.integration.find_first(
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
    """Get AI audit logs with filtering (EU AI Act Art. 12 records)."""
    db = await get_prisma()

    where = {"tenantId": current_user.tenant_id}

    if start_date:
        where["createdAt"] = {"gte": start_date}
    if end_date:
        where.setdefault("createdAt", {})["lte"] = end_date
    if action:
        # Filter by AI decision type (e.g. "extraction", "verification")
        where["decisionType"] = action
    if user_id:
        # AiAuditLog is keyed by task/meeting, not user — filter via tasks
        # assigned to this user.
        user_tasks = await db.task.find_many(
            where={"tenantId": current_user.tenant_id, "assigneeId": str(user_id)},
            select={"id": True},
        )
        where["taskId"] = {"in": [t.id for t in user_tasks]} or ["__none__"]

    total = await db.aiauditlog.count(where=where)
    logs = await db.aiauditlog.find_many(
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
    """
    Compliance posture computed from actual system state.

    Only verifiable facts are reported. Formal certifications (SOC 2,
    ISO 27001) require external audits and are reported as not_certified
    until they exist — this endpoint will never fabricate credentials.
    """
    db = await get_prisma()
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    # Real GDPR signals
    dsr_last_30d = await db.datasubjectrequest.count(
        where={"tenantId": current_user.tenant_id, "createdAt": {"gte": thirty_days_ago}}
    )
    exports_total = await db.complianceexport.count(
        where={"tenantId": current_user.tenant_id}
    )

    # Real EU AI Act signals
    ai_audit_logs = await db.aiauditlog.count(
        where={"tenantId": current_user.tenant_id}
    )
    tasks_needing_review = await db.task.count(
        where={
            "tenantId": current_user.tenant_id,
            "verificationStatus": {"in": ["NEEDS_REVIEW", "PENDING"]},
        }
    )

    pii_redaction_enabled = getattr(settings, "PII_REDACTION_ENABLED", False)

    gdpr_gaps = []
    if not pii_redaction_enabled:
        gdpr_gaps.append("PII redaction is disabled")
    if dsr_last_30d and not exports_total:
        gdpr_gaps.append("DSRs exist but no export capability has been exercised")

    eu_gaps = []
    if ai_audit_logs == 0:
        eu_gaps.append("No AI audit logs recorded yet (Art. 12 record-keeping)")
    if tasks_needing_review == 0:
        eu_gaps.append("Human-in-the-loop review has not processed any tasks yet")

    return {
        "gdpr": {
            "pii_redaction_enabled": pii_redaction_enabled,
            "data_subject_requests_30d": dsr_last_30d,
            "compliance_exports_total": exports_total,
            "erasure_capability": True,   # /compliance/erase-tenant implemented
            "portability_capability": True,  # /compliance/export implemented
            "gaps": gdpr_gaps,
        },
        "eu_ai_act": {
            "ai_audit_log_entries": ai_audit_logs,
            "tasks_pending_human_review": tasks_needing_review,
            "hitl_workflow_present": True,   # verification + HITL resume endpoints
            "model_cards_available": True,   # /compliance/model-cards
            "formal_conformity_assessment": None,  # requires external audit
            "gaps": eu_gaps,
        },
        "soc2": {
            "status": "not_certified",
            "note": "SOC 2 Type II requires an independent CPA audit. No audit has been performed.",
        },
        "iso27001": {
            "status": "not_certified",
            "note": "ISO 27001 certification requires an accredited external audit. None performed.",
        },
        "generated_at": now.isoformat(),
    }


# ─── System Health ───

@router.get("/system/health", summary="Get detailed system health")
async def get_system_health(
    current_user = Depends(require_permission(Permission.TENANT_SETTINGS)),
):
    """Health of every infrastructure dependency, from configured settings."""
    import httpx

    health = {}

    # Database — real query round-trip
    try:
        db = await get_prisma()
        await db.query_raw("SELECT 1")
        health["database"] = "healthy"
    except Exception:
        health["database"] = "unhealthy"

    # Redis
    try:
        import redis.asyncio as redis_lib

        r = redis_lib.from_url(settings.REDIS_URL)
        await r.ping()
        health["redis"] = "healthy"
    except Exception:
        health["redis"] = "unhealthy"

    # Qdrant
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.QDRANT_URL.rstrip('/')}/healthz")
            health["qdrant"] = "healthy" if resp.status_code == 200 else "unhealthy"
    except Exception:
        health["qdrant"] = "unhealthy"

    # Neo4j
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        await asyncio.to_thread(driver.verify_connectivity)
        driver.close()
        health["neo4j"] = "healthy"
    except Exception:
        health["neo4j"] = "unhealthy"

    # MinIO
    try:
        from app.services.storage import StorageService

        storage = StorageService()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: storage.client.bucket_exists(settings.MINIO_BUCKET_AUDIO),
        )
        health["minio"] = "healthy"
    except Exception:
        health["minio"] = "unhealthy"

    checks = [v for v in health.values()]
    if all(v == "healthy" for v in checks):
        health["overall"] = "healthy"
    elif any(v == "unhealthy" for v in checks):
        health["overall"] = "degraded"
    else:
        health["overall"] = "unknown"

    return health


@router.get("/system/metrics", summary="Get system metrics")
async def get_system_metrics(
    current_user = Depends(require_permission(Permission.TENANT_SETTINGS)),
):
    """
    Real system activity metrics.

    Latency/throughput percentiles come from Prometheus/Grafana in a full
    deployment; here we expose genuine database-backed counters only.
    """
    from datetime import datetime, timedelta

    db = await get_prisma()
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)

    meetings_processed_24h = await db.meeting.count(
        where={"updatedAt": {"gte": day_ago}, "status": {"in": ["TRANSCRIBED", "EXTRACTED", "COMPLETED"]}}
    )
    tasks_created_24h = await db.task.count(where={"createdAt": {"gte": day_ago}})
    active_users_24h = await db.user.count(where={"updatedAt": {"gte": day_ago}})
    total_users = await db.user.count()
    llm_calls_logged = await db.aiauditlog.count()
    failed_syncs = await db.task.count(where={"syncStatus": "SYNC_FAILED"})

    celery_workers = []
    try:
        from app.workers.celery_app import celery_app as _celery

        inspector = _celery.control.inspect(timeout=1.5)
        ping = inspector.ping() or {}
        celery_workers = list(ping.keys())
    except Exception:
        pass

    return {
        "meetings_processed_24h": meetings_processed_24h,
        "tasks_created_24h": tasks_created_24h,
        "active_users_24h": active_users_24h,
        "total_users": total_users,
        "llm_decisions_audited": llm_calls_logged,
        "failed_syncs": failed_syncs,
        "celery_workers_online": len(celery_workers),
        "celery_worker_names": celery_workers,
    }


