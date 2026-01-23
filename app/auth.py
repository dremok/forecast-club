from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User

settings = get_settings()
security = HTTPBearer()


def create_magic_link_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.magic_link_expire_minutes
    )
    to_encode = {"sub": email, "type": "magic_link", "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_magic_link_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        if email is None or token_type != "magic_link":
            return None
        return email
    except JWTError:
        return None


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode = {"sub": str(user_id), "type": "access", "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if user_id is None or token_type != "access":
            return None
        return int(user_id)
    except JWTError:
        return None


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = credentials.credentials
    user_id = verify_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
