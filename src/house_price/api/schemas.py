"""Strict request/response schemas matching the versioned OpenAPI contract."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Finite = Annotated[float, Field(allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HousingInstance(StrictModel):
    MedInc: NonNegative
    HouseAge: NonNegative
    AveRooms: Positive
    AveBedrms: NonNegative
    Population: NonNegative
    AveOccup: Positive
    Latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
    Longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class PredictionRequest(StrictModel):
    instances: list[HousingInstance] = Field(min_length=1, max_length=100)


class LivenessResponse(StrictModel):
    status: Literal["alive"] = "alive"


class ReadinessResponse(StrictModel):
    status: Literal["ready"] = "ready"
    environment_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)


class ModelMetricsResponse(StrictModel):
    mae: NonNegative
    mse: NonNegative
    rmse: NonNegative
    r2: Finite


class ModelInfo(StrictModel):
    model_version: str = Field(min_length=1)
    environment_version: str = Field(min_length=1)
    mlflow_run_id: str = Field(min_length=1)
    training_run_id: UUID
    candidate_family: Literal["linear", "ridge", "lasso", "decision_tree", "random_forest"]
    dataset_version: str = Field(min_length=1)
    dataset_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    trained_at: str
    metrics: ModelMetricsResponse


class PredictionResponse(StrictModel):
    predictions: list[Finite] = Field(min_length=1, max_length=100)
    environment_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    mlflow_run_id: str = Field(min_length=1)
    request_id: UUID


class ErrorResponse(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    request_id: UUID


class ValidationIssue(StrictModel):
    location: list[str | int]
    message: str
    type: str


class ValidationErrorResponse(ErrorResponse):
    issues: list[ValidationIssue] = Field(min_length=1)

