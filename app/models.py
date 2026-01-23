import enum
import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    pass


class PredictionStatus(enum.Enum):
    open = "open"
    resolved_yes = "resolved_yes"
    resolved_no = "resolved_no"
    ambiguous = "ambiguous"


class GroupRole(enum.Enum):
    member = "member"
    admin = "admin"


def generate_invite_code() -> str:
    return secrets.token_urlsafe(8)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    memberships: Mapped[list["GroupMembership"]] = relationship(back_populates="user")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="creator")
    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="user")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    invite_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, default=generate_invite_code
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    memberships: Mapped[list["GroupMembership"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    role: Mapped[GroupRole] = mapped_column(Enum(GroupRole), default=GroupRole.member)
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="memberships")
    group: Mapped["Group"] = relationship(back_populates="memberships")


class Prediction(Base):
    __tablename__ = "predictions"

    # Lock-in at 75% of time elapsed (last 25% is locked)
    LOCK_IN_PERCENTAGE = 0.75

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    resolution_criteria: Mapped[str | None] = mapped_column(Text)
    resolution_date: Mapped[datetime] = mapped_column()  # Required
    status: Mapped[PredictionStatus] = mapped_column(
        Enum(PredictionStatus), default=PredictionStatus.open
    )
    resolved_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="predictions")
    creator: Mapped["User"] = relationship(back_populates="predictions")
    forecasts: Mapped[list["Forecast"]] = relationship(
        back_populates="prediction", cascade="all, delete-orphan"
    )

    @property
    def lock_in_at(self) -> datetime:
        """Calculate lock-in deadline: 75% of time from creation to resolution."""
        total_duration = (self.resolution_date - self.created_at).total_seconds()
        lock_in_seconds = total_duration * self.LOCK_IN_PERCENTAGE
        return self.created_at + timedelta(seconds=lock_in_seconds)

    @property
    def is_locked(self) -> bool:
        """Check if forecasts are locked (past lock-in deadline)."""
        return datetime.utcnow() >= self.lock_in_at

    @property
    def time_until_lock(self) -> timedelta | None:
        """Time remaining until lock-in, or None if already locked."""
        if self.is_locked:
            return None
        return self.lock_in_at - datetime.utcnow()


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    probability: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    prediction: Mapped["Prediction"] = relationship(back_populates="forecasts")
    user: Mapped["User"] = relationship(back_populates="forecasts")
