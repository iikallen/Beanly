from fastapi import APIRouter, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text

from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await redis.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependencies unavailable",
        ) from exc
    finally:
        await redis.aclose()
    return {"status": "ok"}
