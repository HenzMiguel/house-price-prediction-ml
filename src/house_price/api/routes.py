"""HTTP routes implementing the OpenAPI contract."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from house_price.api.model_service import ModelNotReadyError, ModelService
from house_price.api.schemas import (
    ErrorResponse,
    LivenessResponse,
    ModelInfo,
    PredictionRequest,
    PredictionResponse,
    ReadinessResponse,
)

router = APIRouter()


def _service(request: Request) -> ModelService:
    return request.app.state.model_service


def _request_id(request: Request) -> UUID:
    return request.state.request_id


@router.get("/health/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ErrorResponse}},
)
async def readiness(request: Request) -> ReadinessResponse:
    champion = _service(request).champion
    if champion is None:
        raise HTTPException(503, "no valid champion is loaded")
    return ReadinessResponse(
        environment_version=request.app.state.environment_version,
        model_version=champion.manifest.model_version,
    )


@router.get("/v1/model", response_model=ModelInfo, responses={503: {"model": ErrorResponse}})
async def model_info(request: Request) -> ModelInfo:
    champion = _service(request).champion
    if champion is None:
        raise HTTPException(503, "no valid champion is loaded")
    manifest = champion.manifest
    return ModelInfo(
        model_version=manifest.model_version,
        environment_version=request.app.state.environment_version,
        mlflow_run_id=manifest.mlflow_run_id,
        training_run_id=manifest.training_run_id,
        candidate_family=manifest.candidate_family.value,
        dataset_version=manifest.dataset.version,
        dataset_checksum=manifest.dataset.sha256,
        trained_at=manifest.promoted_at.isoformat(),
        metrics=manifest.metrics.__dict__,
    )


@router.post(
    "/v1/predictions",
    response_model=PredictionResponse,
    responses={500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def predictions(payload: PredictionRequest, request: Request) -> PredictionResponse:
    service = _service(request)
    champion = service.champion
    if champion is None:
        raise HTTPException(503, "no valid champion is loaded")
    try:
        values = service.predict([item.model_dump() for item in payload.instances])
    except ModelNotReadyError as exc:
        raise HTTPException(503, str(exc)) from exc
    return PredictionResponse(
        predictions=values,
        environment_version=request.app.state.environment_version,
        model_version=champion.manifest.model_version,
        mlflow_run_id=champion.manifest.mlflow_run_id,
        request_id=_request_id(request),
    )

