import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, GroupMembership, GroupRole, User


class TestGroupEndpoints:
    @pytest.mark.asyncio
    async def test_create_group(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/groups",
            headers=auth_headers,
            json={"name": "Test Group", "description": "A test group"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Group"
        assert data["description"] == "A test group"
        assert "invite_code" in data
        assert len(data["invite_code"]) > 0

    @pytest.mark.asyncio
    async def test_create_group_unauthorized(self, client: AsyncClient):
        response = await client.post(
            "/api/groups",
            json={"name": "Test Group"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_group_empty_name(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/groups",
            headers=auth_headers,
            json={"name": ""},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_my_groups(
        self, client: AsyncClient, auth_headers: dict, test_user: User, db: AsyncSession
    ):
        # Create a group with the user as admin
        group = Group(name="My Group")
        db.add(group)
        await db.flush()

        membership = GroupMembership(
            user_id=test_user.id, group_id=group.id, role=GroupRole.admin
        )
        db.add(membership)
        await db.commit()

        response = await client.get("/api/groups", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "My Group"
        assert data[0]["role"] == "admin"

    @pytest.mark.asyncio
    async def test_get_group(
        self, client: AsyncClient, auth_headers: dict, test_user: User, db: AsyncSession
    ):
        group = Group(name="Test Group")
        db.add(group)
        await db.flush()

        membership = GroupMembership(
            user_id=test_user.id, group_id=group.id, role=GroupRole.member
        )
        db.add(membership)
        await db.commit()

        response = await client.get(f"/api/groups/{group.id}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["name"] == "Test Group"

    @pytest.mark.asyncio
    async def test_get_group_not_member(
        self, client: AsyncClient, auth_headers: dict, db: AsyncSession
    ):
        group = Group(name="Other Group")
        db.add(group)
        await db.commit()

        response = await client.get(f"/api/groups/{group.id}", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_join_group(
        self,
        client: AsyncClient,
        second_auth_headers: dict,
        test_user: User,
        db: AsyncSession,
    ):
        # Create a group with the first user
        group = Group(name="Join Test")
        db.add(group)
        await db.flush()

        membership = GroupMembership(
            user_id=test_user.id, group_id=group.id, role=GroupRole.admin
        )
        db.add(membership)
        await db.commit()
        await db.refresh(group)

        # Second user joins via invite code
        response = await client.post(
            f"/api/groups/join?invite_code={group.invite_code}",
            headers=second_auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Join Test"

    @pytest.mark.asyncio
    async def test_join_group_invalid_code(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.post(
            "/api/groups/join?invite_code=invalid",
            headers=auth_headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_join_group_already_member(
        self, client: AsyncClient, auth_headers: dict, test_user: User, db: AsyncSession
    ):
        group = Group(name="Already Joined")
        db.add(group)
        await db.flush()

        membership = GroupMembership(
            user_id=test_user.id, group_id=group.id, role=GroupRole.member
        )
        db.add(membership)
        await db.commit()
        await db.refresh(group)

        response = await client.post(
            f"/api/groups/join?invite_code={group.invite_code}",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "Already a member" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_group_members(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        second_user: User,
        db: AsyncSession,
    ):
        group = Group(name="Members Test")
        db.add(group)
        await db.flush()

        db.add(GroupMembership(user_id=test_user.id, group_id=group.id, role=GroupRole.admin))
        db.add(GroupMembership(user_id=second_user.id, group_id=group.id, role=GroupRole.member))
        await db.commit()

        response = await client.get(f"/api/groups/{group.id}/members", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_leave_group(
        self, client: AsyncClient, auth_headers: dict, test_user: User, db: AsyncSession
    ):
        group = Group(name="Leave Test")
        db.add(group)
        await db.flush()

        membership = GroupMembership(
            user_id=test_user.id, group_id=group.id, role=GroupRole.member
        )
        db.add(membership)
        await db.commit()

        response = await client.delete(f"/api/groups/{group.id}/leave", headers=auth_headers)
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_leave_group_not_member(
        self, client: AsyncClient, auth_headers: dict, db: AsyncSession
    ):
        group = Group(name="Not Member")
        db.add(group)
        await db.commit()

        response = await client.delete(f"/api/groups/{group.id}/leave", headers=auth_headers)
        assert response.status_code == 404
