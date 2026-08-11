from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine
from beanly.core.redis import redis_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await redis_client.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependencies unavailable",
        ) from exc
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "environment": settings.environment,
    }
