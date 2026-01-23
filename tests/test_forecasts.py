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
async def group_with_prediction(
    db: AsyncSession, test_user: User
) -> tuple[Group, Prediction]:
    """Create a group with a prediction."""
    group = Group(name="Forecast Test Group")
    db.add(group)
    await db.flush()

    membership = GroupMembership(
        user_id=test_user.id, group_id=group.id, role=GroupRole.admin
    )
    db.add(membership)
    await db.flush()

    prediction = Prediction(
        group_id=group.id,
        creator_id=test_user.id,
        title="Test Prediction",
        resolution_date=FUTURE_DATE,
    )
    db.add(prediction)
    await db.commit()
    await db.refresh(group)
    await db.refresh(prediction)

    return group, prediction


class TestForecastEndpoints:
    @pytest.mark.asyncio
    async def test_create_forecast(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
    ):
        _, prediction = group_with_prediction

        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={
                "prediction_id": prediction.id,
                "probability": 0.75,
                "reasoning": "I think this is likely",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["probability"] == 0.75
        assert data["reasoning"] == "I think this is likely"
        assert data["prediction_id"] == prediction.id

    @pytest.mark.asyncio
    async def test_create_forecast_probability_bounds(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
    ):
        _, prediction = group_with_prediction

        # Test lower bound
        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": -0.1},
        )
        assert response.status_code == 422

        # Test upper bound
        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": 1.1},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_forecast_at_bounds(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        db: AsyncSession,
    ):
        _, prediction = group_with_prediction

        # 0.0 should be valid
        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": 0.0},
        )
        assert response.status_code == 201

        # Delete the forecast to test 1.0
        forecast_id = response.json()["id"]
        result = await db.get(Forecast, forecast_id)
        await db.delete(result)
        await db.commit()

        # 1.0 should be valid
        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": 1.0},
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_forecast_not_member(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db: AsyncSession,
        test_user: User,
    ):
        # Create group without test user
        group = Group(name="Other Group")
        db.add(group)
        await db.flush()

        # Create another user as member
        other_user = User(email="other@example.com")
        db.add(other_user)
        await db.flush()

        db.add(GroupMembership(user_id=other_user.id, group_id=group.id, role=GroupRole.admin))

        prediction = Prediction(
            group_id=group.id,
            creator_id=other_user.id,
            title="Not My Prediction",
            resolution_date=FUTURE_DATE,
        )
        db.add(prediction)
        await db.commit()
        await db.refresh(prediction)

        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": 0.5},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_forecast_on_resolved_prediction(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        db: AsyncSession,
    ):
        _, prediction = group_with_prediction
        prediction.status = PredictionStatus.resolved_yes
        await db.commit()

        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": 0.5},
        )
        assert response.status_code == 400
        assert "resolved" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_duplicate_forecast(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        test_user: User,
        db: AsyncSession,
    ):
        _, prediction = group_with_prediction

        # Create first forecast
        forecast = Forecast(
            prediction_id=prediction.id,
            user_id=test_user.id,
            probability=0.5,
        )
        db.add(forecast)
        await db.commit()

        # Try to create another
        response = await client.post(
            "/api/forecasts",
            headers=auth_headers,
            json={"prediction_id": prediction.id, "probability": 0.6},
        )
        assert response.status_code == 400
        assert "already have a forecast" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_forecast(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        test_user: User,
        db: AsyncSession,
    ):
        _, prediction = group_with_prediction

        forecast = Forecast(
            prediction_id=prediction.id,
            user_id=test_user.id,
            probability=0.5,
        )
        db.add(forecast)
        await db.commit()
        await db.refresh(forecast)

        response = await client.patch(
            f"/api/forecasts/{forecast.id}",
            headers=auth_headers,
            json={"probability": 0.8, "reasoning": "Updated reasoning"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["probability"] == 0.8
        assert data["reasoning"] == "Updated reasoning"

    @pytest.mark.asyncio
    async def test_update_forecast_not_owner(
        self,
        client: AsyncClient,
        second_auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        test_user: User,
        second_user: User,
        db: AsyncSession,
    ):
        group, prediction = group_with_prediction

        # Add second user to group
        db.add(GroupMembership(
            user_id=second_user.id, group_id=group.id, role=GroupRole.member
        ))

        # First user creates forecast
        forecast = Forecast(
            prediction_id=prediction.id,
            user_id=test_user.id,
            probability=0.5,
        )
        db.add(forecast)
        await db.commit()
        await db.refresh(forecast)

        # Second user tries to update it
        response = await client.patch(
            f"/api/forecasts/{forecast.id}",
            headers=second_auth_headers,
            json={"probability": 0.9},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_forecast_on_resolved(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        test_user: User,
        db: AsyncSession,
    ):
        _, prediction = group_with_prediction

        forecast = Forecast(
            prediction_id=prediction.id,
            user_id=test_user.id,
            probability=0.5,
        )
        db.add(forecast)
        await db.flush()

        prediction.status = PredictionStatus.resolved_no
        await db.commit()
        await db.refresh(forecast)

        response = await client.patch(
            f"/api/forecasts/{forecast.id}",
            headers=auth_headers,
            json={"probability": 0.9},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_list_forecasts_for_prediction(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        test_user: User,
        second_user: User,
        db: AsyncSession,
    ):
        group, prediction = group_with_prediction

        db.add(GroupMembership(
            user_id=second_user.id, group_id=group.id, role=GroupRole.member
        ))

        db.add(Forecast(prediction_id=prediction.id, user_id=test_user.id, probability=0.3))
        db.add(Forecast(prediction_id=prediction.id, user_id=second_user.id, probability=0.7))
        await db.commit()

        response = await client.get(
            f"/api/forecasts/prediction/{prediction.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_list_my_forecasts(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_prediction: tuple[Group, Prediction],
        test_user: User,
        db: AsyncSession,
    ):
        _, prediction = group_with_prediction

        db.add(Forecast(prediction_id=prediction.id, user_id=test_user.id, probability=0.5))
        await db.commit()

        response = await client.get("/api/forecasts/mine", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["probability"] == 0.5
