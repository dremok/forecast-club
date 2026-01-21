# Forecast Club

**Prediction tracker for intellectual communities. Track forecasts, score calibration, compete with friends.**

*"Don't you forget about me" — but for predictions*

## The Problem

Friend groups, podcasters, and pundits constantly make predictions ("AI will cause catastrophe by 2040", "Trump wins 2024", "Bitcoin hits $200K by 2025") but never track them. This makes it impossible to know who's actually good at forecasting vs. who's just confident.

## The Solution

A simple app where you:
1. Create predictions with clear resolution criteria and dates
2. Assign your confidence level (probability)
3. Others in your group add their forecasts
4. When the date arrives, resolve the prediction
5. Everyone gets scored using Brier score (rewards calibration, not just being right)

## Key Differentiator

Unlike Metaculus (complex, public) or Manifold (trading-focused), Forecast Club is:
- **For private groups** — your friend circle, team, or community
- **Simple** — no play money, no trading, just probabilities
- **Calibration-focused** — emphasizes being well-calibrated over being "right"

## MVP Scope (2-week build)

### Week 1: Backend
- [ ] Data models (Prediction, Forecast, User, Group)
- [ ] SQLite database + migrations
- [ ] CRUD API for predictions
- [ ] Forecast submission
- [ ] Brier score calculation
- [ ] Resolution workflow

### Week 2: Frontend + Deploy
- [ ] Simple UI with HTMX (fast, minimal JS)
- [ ] Magic link authentication
- [ ] Prediction feed
- [ ] Leaderboard with calibration charts
- [ ] Deploy to Railway

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | FastAPI | Fast, typed, familiar |
| Database | SQLite → Postgres | Start simple, scale later |
| ORM | SQLAlchemy 2.0 | Async support, mature |
| Frontend | Jinja2 + HTMX | Minimal JS, fast iteration |
| Auth | Magic links | No passwords to manage |
| Hosting | Railway | Simple, cheap ($5/mo) |

## Data Model

```python
class Prediction:
    id: UUID
    text: str                      # "AI causes catastrophe by 2040"
    creator_id: UUID
    group_id: UUID
    created_at: datetime
    resolves_at: datetime
    resolution_criteria: str       # "Defined as >1M deaths attributable to AI"
    status: Literal["open", "resolved_yes", "resolved_no", "ambiguous"]
    resolved_at: datetime | None

class Forecast:
    id: UUID
    prediction_id: UUID
    user_id: UUID
    probability: float             # 0.0 - 1.0
    reasoning: str | None
    created_at: datetime

class User:
    id: UUID
    email: str
    name: str
    created_at: datetime

class Group:
    id: UUID
    name: str
    created_by: UUID
    invite_code: str               # For joining
    created_at: datetime

class GroupMembership:
    user_id: UUID
    group_id: UUID
    joined_at: datetime
```

## Scoring: Brier Score

```python
def brier_score(probability: float, outcome: bool) -> float:
    """
    Lower is better.
    - 0 = perfect (said 100%, was right OR said 0%, was wrong)
    - 1 = maximally wrong (said 100%, was wrong OR said 0%, was right)
    - 0.25 = saying 50% on everything
    """
    actual = 1.0 if outcome else 0.0
    return (probability - actual) ** 2
```

**Examples:**
| Said | Outcome | Brier Score | Interpretation |
|------|---------|-------------|----------------|
| 90%  | Yes     | 0.01        | Excellent |
| 90%  | No      | 0.81        | Terrible |
| 50%  | Either  | 0.25        | Mediocre (no information) |
| 70%  | Yes     | 0.09        | Good |
| 70%  | No      | 0.49        | Bad |

## API Endpoints

```
# Auth
POST   /auth/magic-link           # Send login email
GET    /auth/verify               # Verify magic link token

# Groups
POST   /groups                    # Create group
GET    /groups                    # List my groups
GET    /groups/{id}               # Get group details
POST   /groups/{id}/join          # Join via invite code

# Predictions
POST   /predictions               # Create prediction
GET    /predictions               # List (filter by group, status)
GET    /predictions/{id}          # Get with all forecasts
POST   /predictions/{id}/resolve  # Resolve as yes/no/ambiguous

# Forecasts
POST   /predictions/{id}/forecast # Add your probability
PUT    /forecasts/{id}            # Update forecast (before resolution)

# Stats
GET    /users/{id}/stats          # Brier score, calibration data
GET    /groups/{id}/leaderboard   # Ranked members
```

## Key Screens

1. **Feed** — Open predictions in your groups, sorted by resolution date
2. **Create Prediction** — Text, criteria, date, your initial forecast
3. **Prediction Detail** — See all forecasts, add yours, discuss
4. **Resolve** — Mark as yes/no/ambiguous (creator or group admin)
5. **Leaderboard** — Brier scores + calibration curves
6. **Profile** — Your predictions, accuracy over time, calibration chart

## Calibration Chart

```
Your Calibration (Perfect = diagonal line):

100% |                              *
 80% |                    *
 60% |              *
 40% |        *
 20% |  *
  0% +----+----+----+----+----+----+
     0%  20%  40%  60%  80% 100%
         Your Stated Confidence
```

Interpretation: If you say "70% confident" on 10 predictions, ~7 should resolve YES. This chart shows if you're overconfident, underconfident, or well-calibrated.

## Project Structure

```
forecast-club/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app, middleware
│   ├── config.py             # Settings from env
│   ├── database.py           # SQLAlchemy setup
│   ├── models.py             # SQLAlchemy models
│   ├── schemas.py            # Pydantic schemas
│   ├── auth.py               # Magic link logic
│   ├── scoring.py            # Brier score calculations
│   └── routers/
│       ├── __init__.py
│       ├── auth.py
│       ├── groups.py
│       ├── predictions.py
│       ├── forecasts.py
│       └── stats.py
├── templates/                # Jinja2 templates
│   ├── base.html
│   ├── feed.html
│   ├── prediction.html
│   ├── create.html
│   ├── leaderboard.html
│   └── profile.html
├── static/
│   ├── style.css
│   └── htmx.min.js
├── migrations/               # Alembic migrations
├── tests/
│   ├── test_scoring.py
│   ├── test_predictions.py
│   └── test_api.py
├── .env.example
├── pyproject.toml
├── Dockerfile
└── README.md
```

## Monetization Strategy

### Phase 1: Free (validate)
- Your friend group uses it
- Gather feedback, iterate

### Phase 2: Waitlist + Soft Launch
- "Prediction tracker for intellectual communities"
- Target: rationalist Twitter, Substack authors, podcast hosts
- Product Hunt launch

### Phase 3: Freemium
| Tier | Price | Features |
|------|-------|----------|
| Free | $0 | 1 group, 50 predictions |
| Pro | $5/mo | Unlimited groups, API access, exports |
| Team | $20/mo | Admin controls, custom branding, embeds |

### Phase 4: Growth Features
- **Blog embeds** — Substack authors embed their track record
- **Public profiles** — Forecasters build reputation
- **Prediction markets integration** — Import from Metaculus/Manifold
- **API** — Programmatic prediction creation

## Target Users

1. **Friend groups** — Like Filosoficirkeln
2. **Substack authors** — Track predictions publicly, build credibility
3. **Podcast hosts** — "Let's make this a prediction and track it"
4. **Research teams** — Track hypotheses and outcomes
5. **Companies** — OKR/forecast tracking

## Competitive Landscape

| Tool | Focus | Why we're different |
|------|-------|---------------------|
| Metaculus | Public forecasting | Private groups, simpler |
| Manifold Markets | Play money trading | No trading complexity |
| PredictionBook | Personal tracking | Social/group focus |
| Good Judgment Open | Tournaments | Friend groups, not competitions |

## Success Metrics

- **Week 1**: 5 friends using it
- **Month 1**: 20 users, 3 groups
- **Month 3**: 100 users, Product Hunt launch
- **Month 6**: $500 MRR

## Getting Started

```bash
# Clone
git clone git@github.com:dremok/forecast-club.git
cd forecast-club

# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run
uvicorn app.main:app --reload

# Test
pytest
```

## License

MIT
