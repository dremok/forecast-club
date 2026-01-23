from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Group, GroupMembership, GroupRole, User
from app.schemas import (
    GroupCreate,
    GroupMemberResponse,
    GroupResponse,
    GroupWithMembership,
)

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_data: GroupCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Group:
    """Create a new group. The creator becomes an admin."""
    group = Group(name=group_data.name, description=group_data.description)
    db.add(group)
    await db.flush()

    membership = GroupMembership(
        user_id=current_user.id,
        group_id=group.id,
        role=GroupRole.admin,
    )
    db.add(membership)
    return group


@router.get("", response_model=list[GroupWithMembership])
async def list_my_groups(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """List all groups the current user is a member of."""
    result = await db.execute(
        select(Group, GroupMembership.role)
        .join(GroupMembership)
        .where(GroupMembership.user_id == current_user.id)
    )
    rows = result.all()

    return [
        GroupWithMembership(
            id=group.id,
            name=group.name,
            description=group.description,
            invite_code=group.invite_code,
            created_at=group.created_at,
            role=role,
        )
        for group, role in rows
    ]


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Group:
    """Get a specific group. User must be a member."""
    group = await _get_group_for_member(db, group_id, current_user.id)
    return group


@router.post("/join", response_model=GroupResponse)
async def join_group(
    invite_code: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Group:
    """Join a group using an invite code."""
    result = await db.execute(
        select(Group).where(Group.invite_code == invite_code)
    )
    group = result.scalar_one_or_none()

    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code",
        )

    existing = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already a member of this group",
        )

    membership = GroupMembership(
        user_id=current_user.id,
        group_id=group.id,
        role=GroupRole.member,
    )
    db.add(membership)
    return group


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_group_members(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """List all members of a group."""
    await _get_group_for_member(db, group_id, current_user.id)

    result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.user))
        .where(GroupMembership.group_id == group_id)
    )
    memberships = result.scalars().all()

    return [
        GroupMemberResponse(
            user_id=m.user.id,
            email=m.user.email,
            display_name=m.user.display_name,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m in memberships
    ]


@router.delete("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Leave a group."""
    result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == current_user.id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not a member of this group",
        )

    await db.delete(membership)


async def _get_group_for_member(
    db: AsyncSession, group_id: int, user_id: int
) -> Group:
    """Get a group, verifying the user is a member."""
    result = await db.execute(
        select(Group)
        .join(GroupMembership)
        .where(Group.id == group_id, GroupMembership.user_id == user_id)
    )
    group = result.scalar_one_or_none()

    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found or you are not a member",
        )

    return group


async def get_membership(
    db: AsyncSession, group_id: int, user_id: int
) -> GroupMembership | None:
    """Get membership for a user in a group."""
    result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()
