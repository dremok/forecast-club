from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Forecast, Prediction, PredictionStatus, User
from app.routers.groups import get_membership
from app.schemas import ForecastCreate, ForecastResponse, ForecastUpdate

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.post("", response_model=ForecastResponse, status_code=status.HTTP_201_CREATED)
async def create_forecast(
    forecast_data: ForecastCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Forecast:
    """
    Add a forecast to a prediction.
    Can only forecast on open predictions.
    """
    result = await db.execute(
        select(Prediction).where(Prediction.id == forecast_data.prediction_id)
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

    if prediction.status != PredictionStatus.open:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot forecast on a resolved prediction",
        )

    if prediction.is_locked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forecasts are locked for this prediction",
        )

    existing = await db.execute(
        select(Forecast).where(
            Forecast.prediction_id == forecast_data.prediction_id,
            Forecast.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a forecast for this prediction. Use PATCH to update.",
        )

    forecast = Forecast(
        prediction_id=forecast_data.prediction_id,
        user_id=current_user.id,
        probability=forecast_data.probability,
        reasoning=forecast_data.reasoning,
    )
    db.add(forecast)
    await db.flush()
    return forecast


@router.patch("/{forecast_id}", response_model=ForecastResponse)
async def update_forecast(
    forecast_id: int,
    update_data: ForecastUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Forecast:
    """
    Update an existing forecast.
    Can only update your own forecasts on open predictions.
    """
    result = await db.execute(
        select(Forecast).where(Forecast.id == forecast_id)
    )
    forecast = result.scalar_one_or_none()

    if forecast is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Forecast not found",
        )

    if forecast.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own forecasts",
        )

    prediction_result = await db.execute(
        select(Prediction).where(Prediction.id == forecast.prediction_id)
    )
    prediction = prediction_result.scalar_one()

    if prediction.status != PredictionStatus.open:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update forecast on a resolved prediction",
        )

    if prediction.is_locked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forecasts are locked for this prediction",
        )

    forecast.probability = update_data.probability
    if update_data.reasoning is not None:
        forecast.reasoning = update_data.reasoning

    return forecast


@router.get("/prediction/{prediction_id}", response_model=list[ForecastResponse])
async def list_forecasts_for_prediction(
    prediction_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Forecast]:
    """List all forecasts for a prediction."""
    prediction_result = await db.execute(
        select(Prediction).where(Prediction.id == prediction_id)
    )
    prediction = prediction_result.scalar_one_or_none()

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

    result = await db.execute(
        select(Forecast)
        .where(Forecast.prediction_id == prediction_id)
        .order_by(Forecast.created_at)
    )
    return list(result.scalars().all())


@router.get("/mine", response_model=list[ForecastResponse])
async def list_my_forecasts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Forecast]:
    """List all forecasts by the current user."""
    result = await db.execute(
        select(Forecast)
        .where(Forecast.user_id == current_user.id)
        .order_by(Forecast.created_at.desc())
    )
    return list(result.scalars().all())
