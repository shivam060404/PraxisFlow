from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from uuid import UUID

from app.db.prisma import get_db
from app.schemas import User, UserCreate, PaginatedResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db=Depends(get_db),
):
    """Create a new user."""
    user = await db.user.create(
        data={
            "tenantId": str(user_data.tenant_id),
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
    db=Depends(get_db),
):
    """List users with pagination and search."""
    where = {}
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
    db=Depends(get_db),
):
    """Get a single user by ID."""
    user = await db.user.find_unique(where={"id": str(user_id)})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return user


@router.get("/me/profile", response_model=User)
async def get_current_user_profile(
    db=Depends(get_db),
):
    """Get current user's profile (from JWT)."""
    # TODO: Get user_id from JWT token
    # For now, return first user in tenant
    user = await db.user.find_first(
        where={"tenantId": "00000000-0000-0000-0000-000000000001"}
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return user