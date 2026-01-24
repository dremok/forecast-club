from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    create_access_token,
    create_group_invite_token,
    create_magic_link_token,
    send_group_invite_email,
    send_magic_link_email,
    verify_access_token,
    verify_group_invite_token,
    verify_magic_link_token,
)
from app.config import get_settings
from app.database import get_db
from app.models import (
    Forecast,
    Group,
    GroupMembership,
    GroupRole,
    Prediction,
    PredictionStatus,
    User,
)
from app.scoring import calculate_brier_score, calculate_calibration_buckets

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()

# Cookie name for storing JWT
AUTH_COOKIE = "access_token"


async def get_current_user_optional(
    request: Request,
    db: AsyncSession,
) -> User | None:
    """Get user from cookie, return None if not authenticated."""
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        return None

    user_id = verify_access_token(token)
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def require_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Require authenticated user, redirect to login if not."""
    user = await get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


# ============ Auth Pages ============


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await get_current_user_optional(request, db)
    if user:
        return RedirectResponse("/feed", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "user": None})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await get_current_user_optional(request, db)
    if user:
        return RedirectResponse("/feed", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "user": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: Annotated[str, Form()],
):
    """Handle magic link request via form."""
    token = create_magic_link_token(email)
    magic_link = f"{settings.base_url}/auth/callback?token={token}"

    await send_magic_link_email(email, magic_link)

    return templates.TemplateResponse(
        "check_email.html",
        {"request": request},
    )


@router.get("/auth/callback")
async def auth_callback(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verify magic link and set auth cookie."""
    email = verify_magic_link_token(token)
    if email is None:
        return RedirectResponse("/login?error=invalid", status_code=303)

    # Get or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Create access token and set cookie
    access_token = create_access_token(user.id)
    response = RedirectResponse("/feed", status_code=303)
    response.set_cookie(
        AUTH_COOKIE,
        access_token,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    return response


# ============ Feed ============


@router.get("/feed", response_class=HTMLResponse)
async def feed_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    group_id: int | None = None,
    status: str | None = None,
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get user's groups
    groups_result = await db.execute(
        select(Group)
        .join(GroupMembership)
        .where(GroupMembership.user_id == user.id)
    )
    groups = list(groups_result.scalars().all())

    # Get predictions
    query = (
        select(Prediction)
        .options(
            selectinload(Prediction.group),
            selectinload(Prediction.creator),
            selectinload(Prediction.forecasts),
        )
        .join(Group)
        .join(GroupMembership)
        .where(GroupMembership.user_id == user.id)
    )

    if group_id:
        query = query.where(Prediction.group_id == group_id)

    if status == "open":
        query = query.where(Prediction.status == PredictionStatus.open)
    elif status == "resolved":
        query = query.where(Prediction.status != PredictionStatus.open)

    query = query.order_by(Prediction.created_at.desc())
    result = await db.execute(query)
    predictions = list(result.scalars().all())

    # If HTMX request, return just the list
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/prediction_list.html",
            {"request": request, "predictions": predictions, "user": user},
        )

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "user": user,
            "groups": groups,
            "predictions": predictions,
            "selected_group_id": group_id,
            "status_filter": status,
            "active_page": "feed",
        },
    )


# ============ Predictions ============


@router.get("/predictions/new", response_class=HTMLResponse)
async def new_prediction_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get user's groups
    groups_result = await db.execute(
        select(Group)
        .join(GroupMembership)
        .where(GroupMembership.user_id == user.id)
    )
    groups = list(groups_result.scalars().all())

    if not groups:
        return RedirectResponse("/groups/new", status_code=303)

    return templates.TemplateResponse(
        "create_prediction.html",
        {"request": request, "user": user, "groups": groups},
    )


@router.post("/predictions/new")
async def create_prediction_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    group_id: Annotated[int, Form()],
    title: Annotated[str, Form()],
    resolution_date: Annotated[str, Form()],  # Required
    description: Annotated[str | None, Form()] = None,
    resolution_criteria: Annotated[str | None, Form()] = None,
    probability: Annotated[int, Form()] = 50,
    reasoning: Annotated[str | None, Form()] = None,
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Parse date (required)
    try:
        parsed_date = datetime.strptime(resolution_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resolution date")

    # Create prediction
    prediction = Prediction(
        group_id=group_id,
        creator_id=user.id,
        title=title,
        description=description or None,
        resolution_criteria=resolution_criteria or None,
        resolution_date=parsed_date,
    )
    db.add(prediction)
    await db.flush()

    # Create initial forecast
    forecast = Forecast(
        prediction_id=prediction.id,
        user_id=user.id,
        probability=probability / 100,
        reasoning=reasoning or None,
    )
    db.add(forecast)
    await db.commit()

    return RedirectResponse(f"/predictions/{prediction.id}", status_code=303)


@router.get("/predictions/{prediction_id}", response_class=HTMLResponse)
async def prediction_page(
    request: Request,
    prediction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get prediction with relationships
    result = await db.execute(
        select(Prediction)
        .options(
            selectinload(Prediction.group),
            selectinload(Prediction.creator),
            selectinload(Prediction.forecasts).selectinload(Forecast.user),
        )
        .where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()

    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    # Check membership
    membership_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == prediction.group_id,
            GroupMembership.user_id == user.id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    # Get user's forecast if exists
    user_forecast = next(
        (f for f in prediction.forecasts if f.user_id == user.id), None
    )

    # Calculate Brier scores if resolved (only for locked-in forecasts)
    brier_scores = {}
    if prediction.status != PredictionStatus.open:
        for forecast in prediction.forecasts:
            # Only show scores for forecasts that were locked in
            if forecast.created_at < prediction.lock_in_at:
                score = calculate_brier_score(forecast.probability, prediction.status)
                if score is not None:
                    brier_scores[forecast.id] = score

    # Check if user can resolve
    can_resolve = (
        prediction.creator_id == user.id or membership.role == GroupRole.admin
    )

    return templates.TemplateResponse(
        "prediction.html",
        {
            "request": request,
            "user": user,
            "prediction": prediction,
            "forecasts": prediction.forecasts,
            "user_forecast": user_forecast,
            "can_resolve": can_resolve,
            "brier_scores": brier_scores,
        },
    )


@router.post("/predictions/{prediction_id}/forecast", response_class=HTMLResponse)
async def submit_forecast(
    request: Request,
    prediction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    probability: Annotated[int, Form()],
    reasoning: Annotated[str | None, Form()] = None,
):
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401)

    # Get prediction
    result = await db.execute(
        select(Prediction)
        .options(selectinload(Prediction.forecasts).selectinload(Forecast.user))
        .where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()
    if not prediction or prediction.status != PredictionStatus.open:
        raise HTTPException(status_code=400)

    if prediction.is_locked:
        raise HTTPException(status_code=400, detail="Forecasts are locked")

    # Check for existing forecast
    existing = next(
        (f for f in prediction.forecasts if f.user_id == user.id), None
    )

    if existing:
        existing.probability = probability / 100
        existing.reasoning = reasoning or None
    else:
        forecast = Forecast(
            prediction_id=prediction_id,
            user_id=user.id,
            probability=probability / 100,
            reasoning=reasoning or None,
        )
        db.add(forecast)

    await db.commit()

    # Re-fetch forecasts
    result = await db.execute(
        select(Forecast)
        .options(selectinload(Forecast.user))
        .where(Forecast.prediction_id == prediction_id)
    )
    forecasts = list(result.scalars().all())

    return templates.TemplateResponse(
        "partials/forecasts_list.html",
        {"request": request, "user": user, "forecasts": forecasts, "brier_scores": {}},
    )


@router.post("/predictions/{prediction_id}/resolve")
async def resolve_prediction_page(
    request: Request,
    prediction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    outcome: Annotated[str, Form()],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    result = await db.execute(
        select(Prediction).where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()
    if not prediction:
        raise HTTPException(status_code=404)

    # Check permission
    membership_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == prediction.group_id,
            GroupMembership.user_id == user.id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403)

    can_resolve = (
        prediction.creator_id == user.id or membership.role == GroupRole.admin
    )
    if not can_resolve:
        raise HTTPException(status_code=403)

    # Resolve
    prediction.status = PredictionStatus(outcome)
    prediction.resolved_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse(f"/predictions/{prediction_id}", status_code=303)


@router.post("/predictions/{prediction_id}/delete")
async def delete_prediction(
    request: Request,
    prediction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a resolved prediction (admin only)."""
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    result = await db.execute(
        select(Prediction).where(Prediction.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()
    if not prediction:
        raise HTTPException(status_code=404)

    # Check permission (must be admin or creator)
    membership_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == prediction.group_id,
            GroupMembership.user_id == user.id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403)

    can_delete = (
        prediction.creator_id == user.id or membership.role == GroupRole.admin
    )
    if not can_delete:
        raise HTTPException(status_code=403, detail="Only admins or creator can delete")

    # Only allow deleting resolved predictions
    if prediction.status == PredictionStatus.open:
        raise HTTPException(status_code=400, detail="Cannot delete open predictions")

    # Delete associated forecasts first
    await db.execute(
        select(Forecast).where(Forecast.prediction_id == prediction_id)
    )
    from sqlalchemy import delete
    await db.execute(delete(Forecast).where(Forecast.prediction_id == prediction_id))

    # Delete the prediction
    await db.delete(prediction)
    await db.commit()

    return RedirectResponse("/feed", status_code=303)


# ============ Leaderboard ============


@router.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    group_id: int | None = None,
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get user's groups
    groups_result = await db.execute(
        select(Group)
        .join(GroupMembership)
        .where(GroupMembership.user_id == user.id)
    )
    groups = list(groups_result.scalars().all())

    if not groups:
        return templates.TemplateResponse(
            "leaderboard.html",
            {"request": request, "user": user, "groups": [], "active_page": "leaderboard"},
        )

    # Use first group if none selected
    selected_group_id = group_id or groups[0].id

    # Get leaderboard data
    leaderboard = await _calculate_leaderboard(db, selected_group_id)

    # If HTMX request, return just the content
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/leaderboard_content.html",
            {"request": request, "user": user, "leaderboard": leaderboard},
        )

    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "user": user,
            "groups": groups,
            "selected_group_id": selected_group_id,
            "leaderboard": leaderboard,
            "active_page": "leaderboard",
        },
    )


async def _calculate_leaderboard(db: AsyncSession, group_id: int) -> list[dict]:
    """Calculate leaderboard for a group."""
    # Get members
    members_result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.user))
        .where(GroupMembership.group_id == group_id)
    )
    members = list(members_result.scalars().all())

    # Get resolved prediction IDs
    pred_result = await db.execute(
        select(Prediction.id).where(
            Prediction.group_id == group_id,
            Prediction.status != PredictionStatus.open,
        )
    )
    resolved_ids = set(pred_result.scalars().all())

    if not resolved_ids:
        return []

    leaderboard = []
    for member in members:
        # Get forecasts
        forecast_result = await db.execute(
            select(Forecast)
            .options(selectinload(Forecast.prediction))
            .where(
                Forecast.user_id == member.user_id,
                Forecast.prediction_id.in_(resolved_ids),
            )
        )
        forecasts = list(forecast_result.scalars().all())

        # Only count forecasts that were locked in (created before lock-in deadline)
        locked_forecasts = [
            f for f in forecasts
            if f.created_at < f.prediction.lock_in_at
        ]

        if not locked_forecasts:
            continue

        # Calculate average
        scores = []
        for f in locked_forecasts:
            score = calculate_brier_score(f.probability, f.prediction.status)
            if score is not None:
                scores.append(score)

        if scores:
            avg = sum(scores) / len(scores)
            leaderboard.append({
                "user_id": member.user.id,
                "email": member.user.email,
                "display_name": member.user.display_name,
                "average_brier_score": avg,
                "forecast_count": len(locked_forecasts),
            })

    # Sort by score (lower is better)
    leaderboard.sort(key=lambda x: x["average_brier_score"])

    # Add ranks
    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    return leaderboard


# ============ Profile ============


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get user's groups with membership info
    groups_result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.group))
        .where(GroupMembership.user_id == user.id)
    )
    groups = list(groups_result.scalars().all())

    # Get user's forecasts for stats
    forecasts_result = await db.execute(
        select(Forecast)
        .options(selectinload(Forecast.prediction))
        .where(Forecast.user_id == user.id)
    )
    forecasts = list(forecasts_result.scalars().all())

    # Calculate stats - only count forecasts that were locked in
    resolved = [
        f for f in forecasts
        if f.prediction.status != PredictionStatus.open
        and f.created_at < f.prediction.lock_in_at
    ]
    scores = []
    for f in resolved:
        score = calculate_brier_score(f.probability, f.prediction.status)
        if score is not None:
            scores.append(score)

    stats = {
        "total_forecasts": len(forecasts),
        "resolved_forecasts": len(resolved),
        "average_brier_score": sum(scores) / len(scores) if scores else None,
    }

    # Calculate calibration - only count locked-in forecasts
    calibration_data = [
        (f.probability, f.prediction.status)
        for f in resolved
        if f.prediction.status != PredictionStatus.ambiguous
    ]
    calibration = calculate_calibration_buckets(calibration_data) if calibration_data else []

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "groups": groups,
            "stats": stats,
            "calibration": calibration,
            "active_page": "profile",
        },
    )


# ============ Groups ============


@router.get("/groups", response_class=HTMLResponse)
async def groups_list_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get user's groups with membership info
    groups_result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.group))
        .where(GroupMembership.user_id == user.id)
    )
    groups = list(groups_result.scalars().all())

    return templates.TemplateResponse(
        "groups.html",
        {
            "request": request,
            "user": user,
            "groups": groups,
            "active_page": "groups",
        },
    )


@router.get("/groups/new", response_class=HTMLResponse)
async def new_group_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        "create_group.html",
        {"request": request, "user": user},
    )


@router.post("/groups/new")
async def create_group_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    name: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    group = Group(name=name, description=description or None)
    db.add(group)
    await db.flush()

    membership = GroupMembership(
        user_id=user.id,
        group_id=group.id,
        role=GroupRole.admin,
    )
    db.add(membership)
    await db.commit()

    return RedirectResponse("/feed", status_code=303)


@router.get("/groups/join", response_class=HTMLResponse)
async def join_group_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        "join_group.html",
        {"request": request, "user": user},
    )


@router.post("/groups/join")
async def join_group_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    invite_code: Annotated[str, Form()],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Find group
    result = await db.execute(
        select(Group).where(Group.invite_code == invite_code.strip())
    )
    group = result.scalar_one_or_none()

    if not group:
        return templates.TemplateResponse(
            "join_group.html",
            {"request": request, "user": user, "error": "Invalid invite code"},
        )

    # Check if already member
    existing = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse("/feed", status_code=303)

    # Join
    membership = GroupMembership(
        user_id=user.id,
        group_id=group.id,
        role=GroupRole.member,
    )
    db.add(membership)
    await db.commit()

    return RedirectResponse("/feed", status_code=303)


@router.get("/groups/{group_id}", response_class=HTMLResponse)
async def group_detail_page(
    request: Request,
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_current_user_optional(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get group
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Check membership and get role
    membership_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user.id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    is_admin = membership.role == GroupRole.admin

    # Get all members
    members_result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.user))
        .where(GroupMembership.group_id == group_id)
    )
    members = list(members_result.scalars().all())

    # Get active predictions (open status) with forecasts
    predictions_result = await db.execute(
        select(Prediction)
        .options(selectinload(Prediction.forecasts))
        .where(
            Prediction.group_id == group_id,
            Prediction.status == PredictionStatus.open,
        )
        .order_by(Prediction.created_at.desc())
    )
    predictions = list(predictions_result.scalars().all())

    # Get total prediction count (including resolved)
    all_pred_result = await db.execute(
        select(Prediction).where(Prediction.group_id == group_id)
    )
    prediction_count = len(list(all_pred_result.scalars().all()))

    return templates.TemplateResponse(
        "group_detail.html",
        {
            "request": request,
            "user": user,
            "group": group,
            "members": members,
            "is_admin": is_admin,
            "prediction_count": prediction_count,
            "predictions": predictions,
        },
    )


@router.post("/groups/{group_id}/invite", response_class=HTMLResponse)
async def send_group_invite(
    request: Request,
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    email: Annotated[str, Form()],
):
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401)

    # Get group
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404)

    # Check admin
    membership_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user.id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if not membership or membership.role != GroupRole.admin:
        return templates.TemplateResponse(
            "partials/invite_result.html",
            {"request": request, "success": False, "message": "Only admins can invite members"},
        )

    # Create invite token and link
    token = create_group_invite_token(email, group_id)
    invite_link = f"{settings.base_url}/invite/accept?token={token}"

    # Get inviter display name
    inviter_name = user.display_name or user.email

    # Send email
    await send_group_invite_email(email, inviter_name, group.name, invite_link)

    return templates.TemplateResponse(
        "partials/invite_result.html",
        {"request": request, "success": True, "message": f"Invite sent to {email}"},
    )


@router.get("/invite/accept")
async def accept_group_invite(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Accept a group invite - logs in/registers user and adds to group."""
    result = verify_group_invite_token(token)
    if result is None:
        return RedirectResponse("/login?error=invalid_invite", status_code=303)

    email, group_id = result

    # Verify group exists
    group_result = await db.execute(select(Group).where(Group.id == group_id))
    group = group_result.scalar_one_or_none()
    if not group:
        return RedirectResponse("/login?error=group_not_found", status_code=303)

    # Get or create user
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()

    if user is None:
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Check if already a member
    membership_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user.id,
        )
    )
    existing_membership = membership_result.scalar_one_or_none()

    if not existing_membership:
        # Add to group
        membership = GroupMembership(
            user_id=user.id,
            group_id=group_id,
            role=GroupRole.member,
        )
        db.add(membership)
        await db.commit()

    # Create access token and set cookie
    access_token = create_access_token(user.id)
    response = RedirectResponse(f"/groups/{group_id}", status_code=303)
    response.set_cookie(
        AUTH_COOKIE,
        access_token,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


@router.post("/groups/{group_id}/members/{member_id}/remove", response_class=HTMLResponse)
async def remove_group_member(
    request: Request,
    group_id: int,
    member_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a member from a group (admin only)."""
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401)

    # Check admin permission
    admin_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user.id,
        )
    )
    admin_membership = admin_result.scalar_one_or_none()
    if not admin_membership or admin_membership.role != GroupRole.admin:
        raise HTTPException(status_code=403, detail="Only admins can remove members")

    # Can't remove yourself
    if member_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    # Find and delete the membership
    member_result = await db.execute(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == member_id,
        )
    )
    membership = member_result.scalar_one_or_none()
    if membership:
        await db.delete(membership)
        await db.commit()

    # Get group for template
    group_result = await db.execute(select(Group).where(Group.id == group_id))
    group = group_result.scalar_one_or_none()

    # Get updated members list
    members_result = await db.execute(
        select(GroupMembership)
        .options(selectinload(GroupMembership.user))
        .where(GroupMembership.group_id == group_id)
    )
    members = list(members_result.scalars().all())

    return templates.TemplateResponse(
        "partials/members_list.html",
        {
            "request": request,
            "user": user,
            "group": group,
            "members": members,
            "is_admin": True,
        },
    )