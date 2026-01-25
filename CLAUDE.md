# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Forecast Club is a prediction tracking app for private groups. Users create predictions with probabilities, others add their forecasts, and everyone is scored using Brier scores when predictions resolve.

**Status:** MVP complete - backend API, web frontend, group management, and deployment config ready.

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run development server
uvicorn app.main:app --reload

# Run tests
pytest

# Run single test
pytest tests/test_scoring.py -k test_name
```

## Tech Stack

- **Backend:** FastAPI + SQLAlchemy 2.0 (async)
- **Database:** SQLite (dev) → PostgreSQL (prod)
- **Frontend:** Jinja2 templates + HTMX (minimal JS)
- **Auth:** Magic links (no passwords)
- **Migrations:** Alembic
- **Hosting:** Railway

## Architecture

```
app/
├── main.py          # FastAPI app, middleware
├── config.py        # Settings from env
├── database.py      # SQLAlchemy setup
├── models.py        # SQLAlchemy models
├── schemas.py       # Pydantic schemas
├── auth.py          # Magic link logic
├── scoring.py       # Brier score calculations
└── routers/         # API endpoints by domain
    ├── auth.py
    ├── groups.py
    ├── predictions.py
    ├── forecasts.py
    └── stats.py
templates/           # Jinja2 templates
static/              # CSS, htmx.min.js
migrations/          # Alembic migrations
tests/
```

## Core Domain Concepts

- **Prediction:** A statement with resolution criteria and date (e.g., "Bitcoin hits $200K by 2025")
- **Forecast:** A user's probability assignment to a prediction (0.0-1.0)
- **Group:** Private collection of users who share predictions
- **Lock-in:** Forecasts lock at 75% of time elapsed; only locked forecasts count for scoring
- **Brier Score:** `(probability - actual)²` — lower is better (0 = perfect, 0.25 = no information, 1 = maximally wrong)

## Post-Feature Checklist

After completing any feature, ALWAYS:

1. **Run unit tests** - `pytest` to catch regressions
2. **Start the server** - `uvicorn app.main:app --reload --port 8080`
3. **Browse the webapp** - Use Chrome MCP tools to visually verify:
   - Navigate to affected pages
   - Check for errors (500s, broken layouts)
   - Test the new functionality end-to-end
4. **Fix any issues** before considering the feature complete

## Key Models

- `Prediction` has status: `open | resolved_yes | resolved_no | ambiguous`
- `Prediction` has `lock_in_at` (computed as 75% of time from creation to resolution)
- `Prediction` has `is_locked` property (True if current time >= lock_in_at)
- `Forecast` stores probability (float 0-1) and optional reasoning
- Users belong to Groups via `GroupMembership`
- Only creator or group admin can resolve predictions
- Only forecasts created before lock_in_at count for scoring

## Group Management Features

- **Email Invites:** Admins can invite users by email (`POST /groups/{id}/invite`)
- **Invite Accept:** Link auto-logs in user and adds to group (`GET /invite/accept?token=...`)
- **Member Removal:** Admins can remove non-admin members
- **Group Detail Page:** `/groups/{id}` shows members, active predictions, invite form
- **Groups Tab:** Main navigation has Groups tab listing all user's groups
- **Delete Predictions:** Admins/creators can delete resolved predictions

## Deployment (Railway)

```bash
# Procfile runs migrations automatically on deploy
web: alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

**Required environment variables:**
- `DATABASE_URL` - Railway provides with PostgreSQL addon
- `SECRET_KEY` - Random string for JWT (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- `BASE_URL` - Railway app URL (e.g., `https://forecast-club.up.railway.app`)
- `RESEND_API_KEY` - For sending emails
- `EMAIL_FROM_ADDRESS` - Must be from verified Resend domain
