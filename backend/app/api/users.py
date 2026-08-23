from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from uuid import UUID

from app.db.prisma import get_db
from app.schemas import User, UserCreate, PaginatedResponse
from app.security import get_current_subject, Subject

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Create a new user. Tenant comes from the verified token."""
    user = await db.user.create(
        data={
            "tenantId": subject.tenant_id,
            "email": user_data.email,
            "fullName": user_data.full_name,
            "avatarUrl": user_data.avatar_url,
            "role": user_data.role,
            "clerkUserId": user_data.clerk_user_id,
        }
    )
    return user


@router.get("", response_model=PaginatedResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """List users with pagination and search (tenant-scoped)."""
    where = {"tenantId": subject.tenant_id}
    if search:
        where["OR"] = [
            {"fullName": {"contains": search, "mode": "insensitive"}},
            {"email": {"contains": search, "mode": "insensitive"}},
        ]
    
    total = await db.user.count(where=where)
    users = await db.user.find_many(
        where=where,
        skip=(page - 1) * page_size,
        take=page_size,
        order={"createdAt": "desc"},
    )
    
    return PaginatedResponse(
        items=users,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{user_id}", response_model=User)
async def get_user(
    user_id: UUID,
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Get a single user by ID (tenant-scoped)."""
    user = await db.user.find_first(where={"id": str(user_id), "tenantId": subject.tenant_id})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return user


@router.get("/me/profile", response_model=User)
async def get_current_user_profile(
    subject: Subject = Depends(get_current_subject),
    db=Depends(get_db),
):
    """Get the authenticated user's profile.

    Resolves by internal id first; falls back to the Clerk user id for
    tokens minted before a local user row existed.
    """
    user = await db.user.find_first(
        where={
            "tenantId": subject.tenant_id,
            "OR": [{"id": subject.id}, {"clerkUserId": subject.id}],
        }
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return user