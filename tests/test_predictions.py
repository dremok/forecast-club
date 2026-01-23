from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, GroupMembership, GroupRole, Prediction, PredictionStatus, User

# Helper: far future date for tests
FUTURE_DATE = datetime.utcnow() + timedelta(days=365)


@pytest.fixture
async def group_with_user(db: AsyncSession, test_user: User) -> Group:
    """Create a group with the test user as admin."""
    group = Group(name="Test Group")
    db.add(group)
    await db.flush()

    membership = GroupMembership(
        user_id=test_user.id, group_id=group.id, role=GroupRole.admin
    )
    db.add(membership)
    await db.commit()
    await db.refresh(group)
    return group


class TestPredictionEndpoints:
    @pytest.mark.asyncio
    async def test_create_prediction(
        self, client: AsyncClient, auth_headers: dict, group_with_user: Group
    ):
        response = await client.post(
            "/api/predictions",
            headers=auth_headers,
            json={
                "group_id": group_with_user.id,
                "title": "Test prediction",
                "description": "Will this happen?",
                "resolution_criteria": "Must happen by end of year",
                "resolution_date": FUTURE_DATE.isoformat(),
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test prediction"
        assert data["status"] == "open"
        assert data["group_id"] == group_with_user.id

    @pytest.mark.asyncio
    async def test_create_prediction_not_member(
        self, client: AsyncClient, auth_headers: dict, db: AsyncSession
    ):
        # Create a group without the test user
        group = Group(name="Other Group")
        db.add(group)
        await db.commit()

        response = await client.post(
            "/api/predictions",
            headers=auth_headers,
            json={"group_id": group.id, "title": "Test", "resolution_date": FUTURE_DATE.isoformat()},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_group_predictions(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        # Create some predictions
        for i in range(3):
            pred = Prediction(
                group_id=group_with_user.id,
                creator_id=test_user.id,
                title=f"Prediction {i}",
                resolution_date=FUTURE_DATE,
            )
            db.add(pred)
        await db.commit()

        response = await client.get(
            f"/api/predictions/group/{group_with_user.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert len(response.json()) == 3

    @pytest.mark.asyncio
    async def test_list_predictions_filter_by_status(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        # Create predictions with different statuses
        open_pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Open",
            status=PredictionStatus.open,
            resolution_date=FUTURE_DATE,
        )
        resolved_pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Resolved",
            status=PredictionStatus.resolved_yes,
            resolution_date=FUTURE_DATE,
        )
        db.add_all([open_pred, resolved_pred])
        await db.commit()

        response = await client.get(
            f"/api/predictions/group/{group_with_user.id}?status_filter=open",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Open"

    @pytest.mark.asyncio
    async def test_get_prediction(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Get Test",
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        response = await client.get(
            f"/api/predictions/{pred.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Get Test"
        assert "forecasts" in data

    @pytest.mark.asyncio
    async def test_get_prediction_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/api/predictions/9999", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_prediction_as_creator(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Resolve Test",
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        response = await client.post(
            f"/api/predictions/{pred.id}/resolve",
            headers=auth_headers,
            json={"outcome": "resolved_yes"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved_yes"
        assert data["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_resolve_prediction_as_admin(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        second_user: User,
        db: AsyncSession,
    ):
        # Add second user as regular member
        db.add(GroupMembership(
            user_id=second_user.id,
            group_id=group_with_user.id,
            role=GroupRole.member,
        ))

        # Second user creates prediction
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=second_user.id,
            title="Admin Resolve Test",
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        # Admin (test_user) resolves it
        response = await client.post(
            f"/api/predictions/{pred.id}/resolve",
            headers=auth_headers,
            json={"outcome": "resolved_no"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "resolved_no"

    @pytest.mark.asyncio
    async def test_resolve_prediction_not_authorized(
        self,
        client: AsyncClient,
        second_auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        second_user: User,
        db: AsyncSession,
    ):
        # Add second user as regular member
        db.add(GroupMembership(
            user_id=second_user.id,
            group_id=group_with_user.id,
            role=GroupRole.member,
        ))

        # First user creates prediction
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Not Auth Test",
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        # Second user (not creator, not admin) tries to resolve
        response = await client.post(
            f"/api/predictions/{pred.id}/resolve",
            headers=second_auth_headers,
            json={"outcome": "resolved_yes"},
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_resolve_already_resolved(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Already Resolved",
            status=PredictionStatus.resolved_yes,
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        response = await client.post(
            f"/api/predictions/{pred.id}/resolve",
            headers=auth_headers,
            json={"outcome": "resolved_no"},
        )

        assert response.status_code == 400
        assert "already resolved" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_resolve_to_open_not_allowed(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Open Test",
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        response = await client.post(
            f"/api/predictions/{pred.id}/resolve",
            headers=auth_headers,
            json={"outcome": "open"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_prediction(
        self,
        client: AsyncClient,
        auth_headers: dict,
        group_with_user: Group,
        test_user: User,
        db: AsyncSession,
    ):
        pred = Prediction(
            group_id=group_with_user.id,
            creator_id=test_user.id,
            title="Delete Test",
            resolution_date=FUTURE_DATE,
        )
        db.add(pred)
        await db.commit()
        await db.refresh(pred)

        response = await client.delete(
            f"/api/predictions/{pred.id}",
            headers=auth_headers,
        )

        assert response.status_code == 204
