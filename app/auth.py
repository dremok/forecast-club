from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
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


async def send_magic_link_email(email: str, magic_link: str) -> bool:
    """
    Send magic link via Resend.
    Returns True if sent successfully, False otherwise.
    Falls back to console printing if not configured.
    """
    cfg = get_settings()
    if not cfg.email_enabled:
        _print_magic_link_to_console(email, magic_link)
        return True

    try:
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {cfg.resend_api_key}",
            "Content-Type": "application/json",
        }

        body = f"""Hello!

Click the link below to sign in to Forecast Club:

{magic_link}

This link will expire in {cfg.magic_link_expire_minutes} minutes.

If you didn't request this, you can safely ignore this email.

- Forecast Club"""

        from_address = f"{cfg.email_from_name} <{cfg.email_from_address}>"
        data = {
            "from": from_address,
            "to": [email],
            "subject": "Sign in to Forecast Club",
            "text": body,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)

        if response.status_code == 200:
            return True
        else:
            print(f"Resend error ({response.status_code}): {response.text}")
            _print_magic_link_to_console(email, magic_link)
            return False

    except Exception as e:
        print(f"Failed to send email: {e}")
        _print_magic_link_to_console(email, magic_link)
        return False


def _print_magic_link_to_console(email: str, magic_link: str) -> None:
    """Print magic link to console for development."""
    print(f"\n{'='*50}")
    print(f"Magic link for {email}:")
    print(magic_link)
    print(f"{'='*50}\n")


def create_group_invite_token(email: str, group_id: int) -> str:
    """Create a JWT token encoding email + group_id for group invitations."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.magic_link_expire_minutes
    )
    to_encode = {"email": email, "group_id": group_id, "type": "group_invite", "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_group_invite_token(token: str) -> tuple[str, int] | None:
    """Verify and decode a group invite token. Returns (email, group_id) or None."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        email: str = payload.get("email")
        group_id: int = payload.get("group_id")
        token_type: str = payload.get("type")
        if email is None or group_id is None or token_type != "group_invite":
            return None
        return (email, group_id)
    except JWTError:
        return None


async def send_group_invite_email(
    email: str, inviter_name: str, group_name: str, invite_link: str
) -> bool:
    """
    Send group invitation email via Resend.
    Returns True if sent successfully, False otherwise.
    """
    cfg = get_settings()
    if not cfg.email_enabled:
        _print_invite_link_to_console(email, inviter_name, group_name, invite_link)
        return True

    try:
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {cfg.resend_api_key}",
            "Content-Type": "application/json",
        }

        body = f"""Hi!

{inviter_name} invited you to join '{group_name}' on Forecast Club.

Click the link below to join:

{invite_link}

This link will expire in {cfg.magic_link_expire_minutes} minutes.

- Forecast Club"""

        from_address = f"{cfg.email_from_name} <{cfg.email_from_address}>"
        data = {
            "from": from_address,
            "to": [email],
            "subject": f"Join '{group_name}' on Forecast Club",
            "text": body,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)

        if response.status_code == 200:
            return True
        else:
            print(f"Resend error ({response.status_code}): {response.text}")
            _print_invite_link_to_console(email, inviter_name, group_name, invite_link)
            return False

    except Exception as e:
        print(f"Failed to send invite email: {e}")
        _print_invite_link_to_console(email, inviter_name, group_name, invite_link)
        return False


def _print_invite_link_to_console(
    email: str, inviter_name: str, group_name: str, invite_link: str
) -> None:
    """Print invite link to console for development."""
    print(f"\n{'='*50}")
    print(f"Group invite for {email}:")
    print(f"Invited by: {inviter_name}")
    print(f"Group: {group_name}")
    print(invite_link)
    print(f"{'='*50}\n")
