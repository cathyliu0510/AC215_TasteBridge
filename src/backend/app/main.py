"""TasteBridge API entry point.

Run locally:  uv run uvicorn app.main:app --reload --port 9000
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.artifacts import load_artifacts
from app.config import Settings
from app.feedback import FeedbackStore
from app.routers import books, feedback, health, recommend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("tastebridge")
request_logger = logging.getLogger("tastebridge.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail fast: an invalid artifact folder raises here and the server never starts.
        artifacts = load_artifacts(settings.artifact_dir)
        app.state.artifacts = artifacts
        app.state.feedback_store = FeedbackStore(settings.feedback_path)
        logger.info(
            "Loaded model %s (data %s) with %d books from %s",
            artifacts.model_version,
            artifacts.data_version or "unrecorded",
            len(artifacts.books),
            settings.artifact_dir,
        )
        yield

    app = FastAPI(
        title="TasteBridge API",
        description="Bridge-book recommendations for two readers.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.middleware("http")(log_requests)

    for router in (health.router, books.router, recommend.router, feedback.router):
        app.include_router(router)
    return app


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log method, path, status and duration for every request (SPEC.md section 6)."""
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        request_logger.info(
            "%s %s %d %.1fms", request.method, request.url.path, status_code, duration_ms
        )


app = create_app()
