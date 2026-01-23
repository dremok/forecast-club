from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import (
    auth_router,
    forecasts_router,
    groups_router,
    predictions_router,
    stats_router,
)
from app.routers.pages import router as pages_router

settings = get_settings()

app = FastAPI(
    title="Forecast Club",
    description="Prediction tracking app for private groups",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# API routers (prefixed with /api for clarity)
app.include_router(auth_router, prefix="/api")
app.include_router(groups_router, prefix="/api")
app.include_router(predictions_router, prefix="/api")
app.include_router(forecasts_router, prefix="/api")
app.include_router(stats_router, prefix="/api")

# HTML pages router
app.include_router(pages_router)


@app.get("/health")
async def health():
    return {"status": "healthy"}
