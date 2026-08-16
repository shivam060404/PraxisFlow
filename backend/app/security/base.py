"""
Security Base Module for PraxisFlow
RBAC/ABAC authorization primitives.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class Role(str, Enum):
    """System roles."""
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    BOT = "bot"


class Permission(str, Enum):
    """Fine-grained permissions for authorization."""
    # User management
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_MANAGE = "user:manage"  # Wildcard for all user permissions

    # Meeting management
    MEETING_CREATE = "meeting:create"
    MEETING_READ = "meeting:read"
    MEETING_UPDATE = "meeting:update"
    MEETING_DELETE = "meeting:delete"
    MEETING_MANAGE = "meeting:manage"

    # Task management
    TASK_CREATE = "task:create"
    TASK_READ = "task:read"
    TASK_UPDATE = "task:update"
    TASK_DELETE = "task:delete"
    TASK_MANAGE = "task:manage"

    # Transcript management
    TRANSCRIPT_CREATE = "transcript:create"
    TRANSCRIPT_READ = "transcript:read"
    TRANSCRIPT_UPDATE = "transcript:update"
    TRANSCRIPT_DELETE = "transcript:delete"
    TRANSCRIPT_MANAGE = "transcript:manage"

    # Integration management
    INTEGRATION_CREATE = "integration:create"
    INTEGRATION_READ = "integration:read"
    INTEGRATION_UPDATE = "integration:update"
    INTEGRATION_DELETE = "integration:delete"
    INTEGRATION_SYNC = "integration:sync"
    INTEGRATION_MANAGE = "integration:manage"

    # Admin / Tenant settings
    TENANT_SETTINGS = "tenant:settings"
    BILLING_VIEW = "billing:view"
    BILLING_MANAGE = "billing:manage"

    # Compliance
    COMPLIANCE_EXPORT = "compliance:export"
    AUDIT_LOG_READ = "audit:read"

    # Webhooks
    WEBHOOK_REGISTER = "webhook:register"
    WEBHOOK_READ = "webhook:read"
    WEBHOOK_DELETE = "webhook:delete"


class AttributeKey(str, Enum):
    """ABAC attribute keys."""
    TENANT_ID = "tenant_id"
    USER_ID = "user_id"
    ROLE = "role"
    MEETING_ID = "meeting_id"
    TASK_ID = "task_id"
    INTEGRATION_ID = "integration_id"
    RESOURCE_OWNER_ID = "resource_owner_id"
    DEPARTMENT = "department"
    TEAM = "team"


@dataclass
class Subject:
    """Authorization subject (user, service, etc.)."""
    id: str
    tenant_id: str
    roles: List[Role] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_permission(self, permission: Permission) -> bool:
        # Simple RBAC: admin has all permissions
        if self.has_role(Role.ADMIN):
            return True
        # Check explicit permissions from attributes
        perms = self.attributes.get("permissions", [])
        return permission.value in perms


@dataclass
class Resource:
    """Authorization resource."""
    type: str
    id: str
    tenant_id: str
    owner_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    """Authorization action."""
    permission: Permission
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorizationDecision:
    """Result of an authorization check."""
    allowed: bool
    reason: str = ""
    matched_policy: Optional[str] = None


class PolicyEngine:
    """Base policy engine interface."""
    
    async def evaluate(self, subject: Subject, resource: Resource, action: Action) -> AuthorizationDecision:
        raise NotImplementedError


class OPAPolicyEngine(PolicyEngine):
    """OPA (Open Policy Agent) based policy engine."""
    
    def __init__(self, opa_url: str = "http://opa:8181"):
        self.opa_url = opa_url
    
    async def evaluate(self, subject: Subject, resource: Resource, action: Action) -> AuthorizationDecision:
        # Placeholder - would call OPA HTTP API
        return AuthorizationDecision(allowed=True, reason="OPA evaluation not implemented")


class RBACManager:
    """Role-Based Access Control manager."""
    
    # Default role -> permissions mapping
    ROLE_PERMISSIONS = {
        Role.ADMIN: [p for p in Permission],  # All permissions
        Role.MEMBER: [
            Permission.MEETING_CREATE,
            Permission.MEETING_READ,
            Permission.MEETING_UPDATE,
            Permission.TASK_CREATE,
            Permission.TASK_READ,
            Permission.TASK_UPDATE,
            Permission.TRANSCRIPT_CREATE,
            Permission.TRANSCRIPT_READ,
            Permission.INTEGRATION_READ,
            Permission.INTEGRATION_SYNC,
        ],
        Role.VIEWER: [
            Permission.MEETING_READ,
            Permission.TASK_READ,
            Permission.TRANSCRIPT_READ,
            Permission.INTEGRATION_READ,
        ],
        Role.BOT: [
            Permission.MEETING_CREATE,
            Permission.MEETING_READ,
            Permission.MEETING_UPDATE,
            Permission.TASK_CREATE,
            Permission.TASK_READ,
            Permission.TASK_UPDATE,
            Permission.TRANSCRIPT_CREATE,
            Permission.TRANSCRIPT_READ,
            Permission.INTEGRATION_SYNC,
        ],
    }
    
    def get_permissions_for_role(self, role: Role) -> List[Permission]:
        return self.ROLE_PERMISSIONS.get(role, [])
    
    def role_has_permission(self, role: Role, permission: Permission) -> bool:
        return permission in self.get_permissions_for_role(role)


class ABACManager:
    """Attribute-Based Access Control manager."""
    
    async def evaluate(
        self,
        subject: Subject,
        resource: Resource,
        action: Action,
        policies: List[Dict[str, Any]],
    ) -> AuthorizationDecision:
        # Placeholder - would evaluate ABAC policies
        return AuthorizationDecision(allowed=True, reason="ABAC evaluation not implemented")


class AuthorizationService:
    """High-level authorization service combining RBAC and ABAC."""
    
    def __init__(self):
        self.rbac = RBACManager()
        self.abac = ABACManager()
        self.opa = OPAPolicyEngine()
    
    async def authorize(
        self,
        subject: Subject,
        resource: Resource,
        permission: Permission,
        context: Optional[Dict[str, Any]] = None,
    ) -> AuthorizationDecision:
        """Check if subject has permission on resource."""
        
        # Check RBAC
        for role in subject.roles:
            if self.rbac.role_has_permission(role, permission):
                return AuthorizationDecision(allowed=True, reason=f"RBAC: {role.value} has {permission.value}")
        
        # Check explicit permissions
        if subject.has_permission(permission):
            return AuthorizationDecision(allowed=True, reason="Explicit permission granted")
        
        # Check resource ownership
        if resource.owner_id and resource.owner_id == subject.id:
            return AuthorizationDecision(allowed=True, reason="Resource owner")
        
        # Check tenant isolation
        if subject.tenant_id != resource.tenant_id:
            return AuthorizationDecision(allowed=False, reason="Cross-tenant access denied")
        
        return AuthorizationDecision(allowed=False, reason="No matching permission")


# Global authorization service
_authz_service: Optional[AuthorizationService] = None


def get_authorization_service() -> AuthorizationService:
    """Get global authorization service."""
    global _authz_service
    if _authz_service is None:
        _authz_service = AuthorizationService()
    return _authz_service


# ─── FastAPI Dependency Helpers ───

from fastapi import Depends, HTTPException, Request, status


async def get_current_subject(request: Request) -> Subject:
    """Get current subject from request state (set by TenantIsolationMiddleware)."""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No tenant context",
        )
    
    # In a real implementation, fetch user roles from database
    # For now, create a basic subject
    return Subject(
        id=user_id or "unknown",
        tenant_id=tenant_id,
        roles=[Role.MEMBER],  # Default role
        attributes={},
    )


def require_permission(permission: Permission):
    """FastAPI dependency to require a specific permission."""
    async def checker(request: Request, subject = Depends(get_current_subject)) -> Subject:
        authz = get_authorization_service()
        
        # Create a dummy resource for tenant-level checks
        resource = Resource(
            type="tenant",
            id=subject.tenant_id,
            tenant_id=subject.tenant_id,
        )
        
        action = Action(permission=permission, context={})
        decision = await authz.authorize(subject, resource, action)
        
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {permission.value}",
            )
        
        return subject
    
    return checker


# Resource helpers for common patterns

def meeting_resource(meeting_id: str):
    """Create a meeting resource for authorization."""
    # This would be used with a dependency that fetches the meeting
    pass


def task_resource(task_id: str):
    """Create a task resource for authorization."""
    pass


def integration_resource(integration_id: str):
    """Create an integration resource for authorization."""
    pass