import pytest
from httpx import AsyncClient

from app.auth import create_magic_link_token, verify_magic_link_token
from app.models import User


class TestMagicLinkTokens:
    def test_create_and_verify_magic_link_token(self):
        email = "test@example.com"
        token = create_magic_link_token(email)
        assert token is not None

        verified_email = verify_magic_link_token(token)
        assert verified_email == email

    def test_invalid_token_returns_none(self):
        result = verify_magic_link_token("invalid-token")
        assert result is None

    def test_tampered_token_returns_none(self):
        token = create_magic_link_token("test@example.com")
        tampered = token[:-5] + "xxxxx"
        result = verify_magic_link_token(tampered)
        assert result is None


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_request_magic_link(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/magic-link",
            json={"email": "new@example.com"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Magic link sent to your email"

    @pytest.mark.asyncio
    async def test_request_magic_link_invalid_email(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/magic-link",
            json={"email": "not-an-email"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_verify_magic_link_creates_user(self, client: AsyncClient):
        token = create_magic_link_token("newuser@example.com")
        response = await client.get(f"/api/auth/verify?token={token}")

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_verify_magic_link_existing_user(
        self, client: AsyncClient, test_user: User
    ):
        token = create_magic_link_token(test_user.email)
        response = await client.get(f"/api/auth/verify?token={token}")

        assert response.status_code == 200
        assert "access_token" in response.json()

    @pytest.mark.asyncio
    async def test_verify_invalid_token(self, client: AsyncClient):
        response = await client.get("/api/auth/verify?token=invalid")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ):
        response = await client.get("/api/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["id"] == test_user.id

    @pytest.mark.asyncio
    async def test_get_me_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/auth/me")
        assert response.status_code == 401  # No auth header

    @pytest.mark.asyncio
    async def test_get_me_invalid_token(self, client: AsyncClient):
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_update_me(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ):
        response = await client.patch(
            "/api/auth/me",
            headers=auth_headers,
            json={"display_name": "New Name"},
        )

        assert response.status_code == 200
        assert response.json()["display_name"] == "New Name"
