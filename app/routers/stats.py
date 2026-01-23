from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Forecast, GroupMembership, Prediction, PredictionStatus, User
from app.routers.groups import get_membership
from app.schemas import CalibrationBucket, LeaderboardEntry, UserStats
from app.scoring import calculate_average_brier_score, calculate_calibration_buckets

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/me", response_model=UserStats)
async def get_my_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserStats:
    """Get stats for the current user across all groups."""
    result = await db.execute(
        select(Forecast)
        .options(selectinload(Forecast.prediction))
        .where(Forecast.user_id == current_user.id)
    )
    forecasts = result.scalars().all()

    # Only count forecasts that were locked in (created before lock-in deadline)
    resolved_forecasts = [
        (f.probability, f.prediction.status)
        for f in forecasts
        if f.prediction.status != PredictionStatus.open
        and f.created_at < f.prediction.lock_in_at
    ]

    avg_score = calculate_average_brier_score(resolved_forecasts)

    return UserStats(
        user_id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        total_forecasts=len(forecasts),
        resolved_forecasts=len(resolved_forecasts),
        average_brier_score=avg_score,
    )


@router.get("/group/{group_id}/leaderboard", response_model=list[LeaderboardEntry])
async def get_group_leaderboard(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LeaderboardEntry]:
    """Get the leaderboard for a group, sorted by average Brier score (lower is better)."""
    membership = await get_membership(db, group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=404,
            detail="Group not found or you are not a member",
        )

    members_result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.user))
        .where(GroupMembership.group_id == group_id)
    )
    members = members_result.scalars().all()

    prediction_ids_result = await db.execute(
        select(Prediction.id).where(
            Prediction.group_id == group_id,
            Prediction.status != PredictionStatus.open,
        )
    )
    resolved_prediction_ids = set(prediction_ids_result.scalars().all())

    leaderboard = []
    for member in members:
        forecast_result = await db.execute(
            select(Forecast)
            .options(selectinload(Forecast.prediction))
            .where(
                Forecast.user_id == member.user_id,
                Forecast.prediction_id.in_(resolved_prediction_ids),
            )
        )
        forecasts = forecast_result.scalars().all()

        # Only count forecasts that were locked in (created before lock-in deadline)
        locked_forecasts = [
            f for f in forecasts
            if f.created_at < f.prediction.lock_in_at
        ]

        if not locked_forecasts:
            continue

        forecast_data = [(f.probability, f.prediction.status) for f in locked_forecasts]
        avg_score = calculate_average_brier_score(forecast_data)

        if avg_score is not None:
            leaderboard.append({
                "user_id": member.user.id,
                "email": member.user.email,
                "display_name": member.user.display_name,
                "average_brier_score": avg_score,
                "forecast_count": len(locked_forecasts),
            })

    leaderboard.sort(key=lambda x: x["average_brier_score"])

    return [
        LeaderboardEntry(rank=i + 1, **entry)
        for i, entry in enumerate(leaderboard)
    ]


@router.get("/me/calibration", response_model=list[CalibrationBucket])
async def get_my_calibration(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CalibrationBucket]:
    """Get calibration data for the current user."""
    result = await db.execute(
        select(Forecast)
        .options(selectinload(Forecast.prediction))
        .where(Forecast.user_id == current_user.id)
    )
    forecasts = result.scalars().all()

    # Only count forecasts that were locked in (created before lock-in deadline)
    resolved_forecasts = [
        (f.probability, f.prediction.status)
        for f in forecasts
        if f.prediction.status != PredictionStatus.open
        and f.created_at < f.prediction.lock_in_at
    ]

    return calculate_calibration_buckets(resolved_forecasts)


@router.get("/group/{group_id}/user/{user_id}", response_model=UserStats)
async def get_user_stats_in_group(
    group_id: int,
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserStats:
    """Get stats for a specific user in a group."""
    membership = await get_membership(db, group_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=404,
            detail="Group not found or you are not a member",
        )

    target_membership = await get_membership(db, group_id, user_id)
    if target_membership is None:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this group",
        )

    user_result = await db.execute(select(User).where(User.id == user_id))
    target_user = user_result.scalar_one()

    prediction_ids_result = await db.execute(
        select(Prediction.id).where(Prediction.group_id == group_id)
    )
    group_prediction_ids = set(prediction_ids_result.scalars().all())

    forecast_result = await db.execute(
        select(Forecast)
        .options(selectinload(Forecast.prediction))
        .where(
            Forecast.user_id == user_id,
            Forecast.prediction_id.in_(group_prediction_ids),
        )
    )
    forecasts = forecast_result.scalars().all()

    # Only count forecasts that were locked in (created before lock-in deadline)
    resolved_forecasts = [
        (f.probability, f.prediction.status)
        for f in forecasts
        if f.prediction.status != PredictionStatus.open
        and f.created_at < f.prediction.lock_in_at
    ]

    avg_score = calculate_average_brier_score(resolved_forecasts)

    return UserStats(
        user_id=target_user.id,
        email=target_user.email,
        display_name=target_user.display_name,
        total_forecasts=len(forecasts),
        resolved_forecasts=len(resolved_forecasts),
        average_brier_score=avg_score,
    )
