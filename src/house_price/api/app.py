"""FastAPI application with safe errors, correlated logs, and minute heartbeats."""

import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from house_price.api.model_service import ModelService
from house_price.api.routes import router
from house_price.logging import configure_logging, log_context
from house_price.registry.loader import ChampionLoader
from house_price.tracking.observability import ObservabilityRepository

LOGGER = logging.getLogger(__name__)


class InferenceMetrics:
    def __init__(
        self,
        environment_version: str,
        model_service: ModelService,
        repository: ObservabilityRepository | None,
        *,
        window_seconds: int = 60,
    ) -> None:
        self.environment_version = environment_version
        self.model_service = model_service
        self.repository = repository
        self.window_seconds = window_seconds
        self.window_started_at = datetime.now(UTC).replace(second=0, microsecond=0)
        self.request_count = 0
        self.error_count = 0
        self.latencies: deque[float] = deque()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="inference-heartbeat")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self.flush()

    async def record(self, latency_ms: float, failed: bool) -> None:
        async with self._lock:
            self.request_count += 1
            self.error_count += int(failed)
            self.latencies.append(latency_ms)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.window_seconds)
            await self.flush()

    async def flush(self) -> None:
        champion = self.model_service.champion
        model_version = champion.manifest.model_version if champion else "none"
        health = "ready" if champion else "unavailable"
        async with self._lock:
            latencies = np.asarray(self.latencies, dtype=float)
            values: dict[str, Any] = {
                "window_started_at": self.window_started_at,
                "window_seconds": self.window_seconds,
                "environment_version": self.environment_version,
                "model_version": model_version,
                "health_status": health,
                "request_count": self.request_count,
                "error_count": self.error_count,
                "latency_p50_ms": float(np.percentile(latencies, 50))
                if len(latencies)
                else None,
                "latency_p95_ms": float(np.percentile(latencies, 95))
                if len(latencies)
                else None,
                "latency_p99_ms": float(np.percentile(latencies, 99))
                if len(latencies)
                else None,
                "latency_max_ms": float(latencies.max()) if len(latencies) else None,
                "recorded_at": datetime.now(UTC),
            }
            self.window_started_at = datetime.now(UTC).replace(second=0, microsecond=0)
            self.request_count = 0
            self.error_count = 0
            self.latencies.clear()
        if self.repository:
            try:
                self.repository.upsert_inference_metric(values)
            except Exception:
                LOGGER.exception(
                    "inference_metrics_publish_failed",
                    extra={
                        "environment_version": self.environment_version,
                        "model_version": model_version,
                        "stage": "metrics",
                    },
                )


def _error(status: int, code: str, message: str, request_id: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "request_id": request_id, **extra},
    )


def create_app(
    *,
    model_registry_path: Path | None = None,
    environment_version: str | None = None,
    repository: ObservabilityRepository | None = None,
    poll_seconds: float = 2.0,
    heartbeat_seconds: int = 60,
) -> FastAPI:
    root = model_registry_path or Path(os.getenv("MODEL_REGISTRY_PATH", "/model-registry"))
    revision = environment_version or os.getenv("ENVIRONMENT_VERSION", "local-dev")
    service = ModelService(ChampionLoader(root), poll_seconds=poll_seconds)
    if repository is None and os.getenv("DATABASE_URL"):
        repository = ObservabilityRepository(os.environ["DATABASE_URL"])
    metrics = InferenceMetrics(
        revision, service, repository, window_seconds=heartbeat_seconds
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(os.getenv("LOG_LEVEL", "INFO"))
        await service.start()
        await metrics.start()
        yield
        await metrics.stop()
        await service.stop()

    application = FastAPI(title="House Price Prediction API", version="1.0.0", lifespan=lifespan)
    application.state.model_service = service
    application.state.environment_version = revision
    application.state.inference_metrics = metrics

    @application.middleware("http")
    async def correlation_and_metrics(request: Request, call_next):
        request_id = uuid4()
        request.state.request_id = request_id
        started = perf_counter()
        failed = False
        with log_context(
            request_id=str(request_id),
            environment_version=revision,
            model_version=service.champion.manifest.model_version if service.champion else None,
            training_run_id=str(service.champion.manifest.training_run_id)
            if service.champion
            else None,
        ):
            try:
                response = await call_next(request)
                failed = response.status_code >= 500
                return response
            except Exception:
                failed = True
                raise
            finally:
                if request.url.path == "/v1/predictions":
                    await metrics.record((perf_counter() - started) * 1000, failed)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return _error(
            exc.status_code,
            "model_not_ready" if exc.status_code == 503 else "http_error",
            str(exc.detail),
            str(request.state.request_id),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        issues = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return _error(
            422,
            "validation_error",
            "request validation failed",
            str(request.state.request_id),
            issues=issues,
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("unexpected_request_failure", exc_info=exc)
        return _error(
            500,
            "internal_error",
            "unexpected internal error",
            str(request.state.request_id),
        )

    application.include_router(router)
    return application


app = create_app()


def run() -> None:
    uvicorn.run("house_price.api.app:app", host="0.0.0.0", port=8000)

