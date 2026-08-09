from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from beanly.api.health import router as health_router
from beanly.api.router import api_v1_router
from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine
from beanly.core.exceptions.handlers import register_exception_handlers
from beanly.core.logging.config import configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


configure_logging()
app = FastAPI(title="Beanly API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(api_v1_router)
