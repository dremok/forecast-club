from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import GroupMembership, GroupRole, Prediction, PredictionStatus, User
from app.routers.groups import get_membership
from app.schemas import (
    PredictionCreate,
    PredictionResponse,
    PredictionWithForecasts,
    ResolveRequest,
)

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.post("", response_model=PredictionResponse, status_code=status.HTTP_201_CREATED)
async def create_prediction(
    prediction_data: PredictionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Prediction:
    """Create a new prediction in a group."""
    membership = await get_membership(db, prediction_data.group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )

    prediction = Prediction(
        group_id=prediction_data.group_id,
        creator_id=current_user.id,
        title=prediction_data.title,
        description=prediction_data.description,
        resolution_criteria=prediction_data.resolution_criteria,
        resolution_date=prediction_data.resolution_date,
    )
    db.add(prediction)
    await db.flush()
    return prediction


@router.get("/group/{group_id}", response_model=list[PredictionResponse])
async def list_group_predictions(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: PredictionStatus | None = None,
) -> list[Prediction]:
    """List all predictions in a group."""
    membership = await get_membership(db, group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )

    query = select(Prediction).where(Prediction.group_id == group_id)
    if status_filter:
        query = query.where(Prediction.status == status_filter)
    query = query.order_by(Prediction.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{prediction_id}", response_model=PredictionWithForecasts)
async def get_prediction(
    prediction_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Prediction:
    """Get a prediction with all its forecasts."""
    result = await db.execute(
        select(Prediction)
        .options(selectinload(Prediction.forecasts))
        .where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()

    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction not found",
        )

    membership = await get_membership(db, prediction.group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )

    return prediction


@router.post("/{prediction_id}/resolve", response_model=PredictionResponse)
async def resolve_prediction(
    prediction_id: int,
    resolve_data: ResolveRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Prediction:
    """
    Resolve a prediction.
    Only the creator or a group admin can resolve.
    """
    if resolve_data.outcome == PredictionStatus.open:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot resolve to 'open' status",
        )

    result = await db.execute(
        select(Prediction).where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()

    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction not found",
        )

    if prediction.status != PredictionStatus.open:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prediction is already resolved",
        )

    membership = await get_membership(db, prediction.group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )

    can_resolve = (
        prediction.creator_id == current_user.id or membership.role == GroupRole.admin
    )
    if not can_resolve:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator or group admin can resolve this prediction",
        )

    prediction.status = resolve_data.outcome
    prediction.resolved_at = datetime.now(timezone.utc)
    return prediction


@router.delete("/{prediction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prediction(
    prediction_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """
    Delete a prediction.
    Only the creator or a group admin can delete.
    """
    result = await db.execute(
        select(Prediction).where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()

    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction not found",
        )

    membership = await get_membership(db, prediction.group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )

    can_delete = (
        prediction.creator_id == current_user.id or membership.role == GroupRole.admin
    )
    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator or group admin can delete this prediction",
        )

    await db.delete(prediction)
