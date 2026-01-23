from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Forecast,
    Group,
    GroupMembership,
    GroupRole,
    Prediction,
    PredictionStatus,
    User,
)

# Helper: far future date for tests
FUTURE_DATE = datetime.utcnow() + timedelta(days=365)


@pytest.fixture
async def group_with_resolved_predictions(
    db: AsyncSession, test_user: User, second_user: User
) -> tuple[Group, list[Prediction]]:
    """Create a group with resolved predictions and forecasts."""
    group = Group(name="Stats Test Group")
    db.add(group)
    await db.flush()

    db.add(GroupMembership(user_id=test_user.id, group_id=group.id, role=GroupRole.admin))
    db.add(GroupMembership(user_id=second_user.id, group_id=group.id, role=GroupRole.member))

    # Create predictions
    pred1 = Prediction(
        group_id=group.id,
        creator_id=test_user.id,
        title="Resolved Yes",
        status=PredictionStatus.resolved_yes,
        resolution_date=FUTURE_DATE,
    )
    pred2 = Prediction(
        group_id=group.id,
        creator_id=test_user.id,
        title="Resolved No",
        status=PredictionStatus.resolved_no,
        resolution_date=FUTURE_DATE,
    )
    pred3 = Prediction(
        group_id=group.id,
        creator_id=test_user.id,
        title="Still Open",
        status=PredictionStatus.open,
        resolution_date=FUTURE_DATE,
    )
    db.add_all([pred1, pred2, pred3])
    await db.flush()

    # Add forecasts
    # test_user: 0.8 on yes (score 0.04), 0.2 on no (score 0.04) - avg 0.04
    db.add(Forecast(prediction_id=pred1.id, user_id=test_user.id, probability=0.8))
    db.add(Forecast(prediction_id=pred2.id, user_id=test_user.id, probability=0.2))

    # second_user: 0.5 on yes (score 0.25), 0.5 on no (score 0.25) - avg 0.25
    db.add(Forecast(prediction_id=pred1.id, user_id=second_user.id, probability=0.5))
    db.add(Forecast(prediction_id=pred2.id, user_id=second_user.id, probability=0.5))

    await db.commit()
    await db.refresh(group)

    return group, [pred1, pred2, pred3]


class TestStatsEndpoints:
    @pytest.mark.asyncio
    async def test_get_my_stats(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_resolved_predictions: tuple[Group, list[Prediction]],
    ):
        response = await client.get("/api/stats/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_forecasts"] == 2
        assert data["resolved_forecasts"] == 2
        assert abs(data["average_brier_score"] - 0.04) < 0.001

    @pytest.mark.asyncio
    async def test_get_my_stats_no_forecasts(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/api/stats/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_forecasts"] == 0
        assert data["resolved_forecasts"] == 0
        assert data["average_brier_score"] is None

    @pytest.mark.asyncio
    async def test_get_leaderboard(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_resolved_predictions: tuple[Group, list[Prediction]],
    ):
        group, _ = group_with_resolved_predictions

        response = await client.get(
            f"/api/stats/group/{group.id}/leaderboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        # test_user should be #1 with lower Brier score
        assert data[0]["rank"] == 1
        assert abs(data[0]["average_brier_score"] - 0.04) < 0.001

        # second_user should be #2
        assert data[1]["rank"] == 2
        assert abs(data[1]["average_brier_score"] - 0.25) < 0.001

    @pytest.mark.asyncio
    async def test_get_leaderboard_not_member(
        self, client: AsyncClient, auth_headers: dict, db: AsyncSession
    ):
        group = Group(name="Other Group")
        db.add(group)
        await db.commit()

        response = await client.get(
            f"/api/stats/group/{group.id}/leaderboard",
            headers=auth_headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_my_calibration(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_resolved_predictions: tuple[Group, list[Prediction]],
    ):
        response = await client.get("/api/stats/me/calibration", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        # We have forecasts at 0.8 and 0.2, so should have 2 buckets
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_user_stats_in_group(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_user: User,
        group_with_resolved_predictions: tuple[Group, list[Prediction]],
    ):
        group, _ = group_with_resolved_predictions

        response = await client.get(
            f"/api/stats/group/{group.id}/user/{second_user.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == second_user.id
        assert data["total_forecasts"] == 2
        assert abs(data["average_brier_score"] - 0.25) < 0.001

    @pytest.mark.asyncio
    async def test_get_user_stats_user_not_in_group(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db: AsyncSession,
    ):
        # Create a group with test_user
        group = Group(name="My Group")
        db.add(group)
        await db.flush()
        db.add(GroupMembership(user_id=test_user.id, group_id=group.id, role=GroupRole.admin))

        # Create another user not in the group
        other_user = User(email="other@example.com")
        db.add(other_user)
        await db.commit()

        response = await client.get(
            f"/api/stats/group/{group.id}/user/{other_user.id}",
            headers=auth_headers,
        )
        assert response.status_code == 404
