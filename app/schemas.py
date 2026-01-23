from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import GroupRole, PredictionStatus


# Auth
class MagicLinkRequest(BaseModel):
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# User
class UserBase(BaseModel):
    email: EmailStr
    display_name: str | None = None


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    display_name: str | None = None


# Group
class GroupBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class GroupCreate(GroupBase):
    pass


class GroupResponse(GroupBase):
    id: int
    invite_code: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupWithMembership(GroupResponse):
    role: GroupRole


class GroupMemberResponse(BaseModel):
    user_id: int
    email: str
    display_name: str | None
    role: GroupRole
    joined_at: datetime

    model_config = {"from_attributes": True}


# Prediction
class PredictionBase(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    resolution_criteria: str | None = None
    resolution_date: datetime  # Required


class PredictionCreate(PredictionBase):
    group_id: int


class PredictionResponse(PredictionBase):
    id: int
    group_id: int
    creator_id: int
    status: PredictionStatus
    resolved_at: datetime | None
    created_at: datetime
    lock_in_at: datetime
    is_locked: bool

    model_config = {"from_attributes": True}


class PredictionWithForecasts(PredictionResponse):
    forecasts: list["ForecastResponse"]


class ResolveRequest(BaseModel):
    outcome: PredictionStatus = Field(
        description="Must be resolved_yes, resolved_no, or ambiguous"
    )


# Forecast
class ForecastBase(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None


class ForecastCreate(ForecastBase):
    prediction_id: int


class ForecastUpdate(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None


class ForecastResponse(ForecastBase):
    id: int
    prediction_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ForecastWithUser(ForecastResponse):
    user: UserResponse


class ForecastWithScore(ForecastResponse):
    brier_score: float | None = None


# Stats
class UserStats(BaseModel):
    user_id: int
    email: str
    display_name: str | None
    total_forecasts: int
    resolved_forecasts: int
    average_brier_score: float | None


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    email: str
    display_name: str | None
    average_brier_score: float
    forecast_count: int


class CalibrationBucket(BaseModel):
    bucket_start: float
    bucket_end: float
    predicted_probability: float
    actual_frequency: float
    count: int


# Rebuild models for forward references
PredictionWithForecasts.model_rebuild()
