from app.routers.auth import router as auth_router
from app.routers.groups import router as groups_router
from app.routers.predictions import router as predictions_router
from app.routers.forecasts import router as forecasts_router
from app.routers.stats import router as stats_router

__all__ = [
    "auth_router",
    "groups_router",
    "predictions_router",
    "forecasts_router",
    "stats_router",
]
