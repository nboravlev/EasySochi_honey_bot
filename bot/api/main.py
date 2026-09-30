"""HTTP API витрины. Запуск: `uvicorn api.main:app` (в контейнере — команда `api`, см. entrypoint.sh).

Фронтенд (web/) и фото (/media/) в бою раздаёт nginx контейнера web_honey; API отдаёт фото сам —
для локальной разработки и тестов.
"""
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from telegram.request import BaseRequest

from api import admin
from api.routes import account, public
from api.notifier import Notifier
from config import get_settings
from db import db_async
from utils.logging_config import bind_update_context, flush_logs, setup_logging, structured_logger

API_LOG_FILE = "api_structured.log"


def create_app(telegram_request: BaseRequest | None = None, configure_logging: bool = True) -> FastAPI:
    """telegram_request — подмена HTTP-клиента Telegram в тестах."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if configure_logging:
            setup_logging(log_dir=settings.log_dir, log_level=settings.log_level, file_name=API_LOG_FILE)
        app.state.notifier = Notifier(settings.bot_token, request=telegram_request)
        structured_logger.info("API started", action="api_started")
        yield
        await app.state.notifier.close()
        await db_async.engine.dispose()
        if configure_logging:
            flush_logs()

    app = FastAPI(
        title="KrasPolHoney API", lifespan=lifespan,
        docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        bind_update_context(request_id=uuid.uuid4().hex[:12])
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            structured_logger.error(
                f"Unhandled API error: {exc!r}", action="api_unhandled_error", exception=exc,
                context={"method": request.method, "path": request.url.path},
            )
            return JSONResponse({"detail": "Внутренняя ошибка. Попробуйте позже."}, status_code=500)
        if response.status_code >= 400 or request.method != "GET":
            structured_logger.info(
                f"{request.method} {request.url.path} → {response.status_code}", action="api_request",
                context={"status": response.status_code, "ms": round((time.perf_counter() - started) * 1000)},
            )
        return response

    app.include_router(public.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(admin.router)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok"}

    app.mount("/media", StaticFiles(directory=settings.media_dir, check_dir=False), name="media")
    return app


app = create_app()
