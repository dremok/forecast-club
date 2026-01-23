from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_magic_link_token,
    get_current_user,
    verify_magic_link_token,
)
from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import MagicLinkRequest, TokenResponse, UserResponse, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/magic-link")
async def request_magic_link(
    request: MagicLinkRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Request a magic link for email-based authentication.
    In debug mode, the link is printed to console.
    In production, this would send an email.
    """
    token = create_magic_link_token(request.email)
    magic_link = f"{settings.base_url}/auth/verify?token={token}"

    if settings.debug:
        print(f"\n{'='*50}")
        print(f"Magic link for {request.email}:")
        print(magic_link)
        print(f"{'='*50}\n")

    return {"message": "Magic link sent to your email"}


@router.get("/verify", response_model=TokenResponse)
async def verify_magic_link(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """
    Verify a magic link token and return an access token.
    Creates the user if they don't exist.
    """
    email = verify_magic_link_token(token)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired magic link",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email)
        db.add(user)
        await db.flush()

    access_token = create_access_token(user.id)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current authenticated user."""
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    update: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Update the current user's profile."""
    if update.display_name is not None:
        current_user.display_name = update.display_name
    return current_user
