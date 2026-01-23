import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import User

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Create tables and yield a database session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with database override."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db: AsyncSession) -> User:
    """Create a test user."""
    user = User(email="test@example.com", display_name="Test User")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
async def auth_headers(test_user: User) -> dict[str, str]:
    """Get auth headers for the test user."""
    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def second_user(db: AsyncSession) -> User:
    """Create a second test user."""
    user = User(email="second@example.com", display_name="Second User")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
async def second_auth_headers(second_user: User) -> dict[str, str]:
    """Get auth headers for the second user."""
    token = create_access_token(second_user.id)
    return {"Authorization": f"Bearer {token}"}
