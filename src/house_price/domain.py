"""Shared domain types and deterministic state rules."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

FEATURE_NAMES = (
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
)


class CandidateFamily(StrEnum):
    LINEAR = "linear"
    RIDGE = "ridge"
    LASSO = "lasso"
    DECISION_TREE = "decision_tree"
    RANDOM_FOREST = "random_forest"


FAMILY_ORDER = tuple(CandidateFamily)


class TrainingStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    OPTIMIZING = "optimizing"
    EVALUATING = "evaluating"
    PUBLISHING_METRICS = "publishing_metrics"
    PROMOTING = "promoting"
    SUCCEEDED = "succeeded"
    SUCCEEDED_NO_PROMOTION = "succeeded_no_promotion"
    SKIPPED_CONCURRENT = "skipped_concurrent"
    FAILED = "failed"


class HealthStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ModelMetrics:
    mae: float
    mse: float
    rmse: float
    r2: float


@dataclass
class ModelCandidate:
    training_run_id: str
    family: CandidateFamily
    mlflow_run_id: str
    best_trial_number: int
    parameters: dict[str, Any]
    metrics: ModelMetrics
    artifact_uri: str = ""
    eligible: bool = False
    ineligibility_reasons: list[str] = field(default_factory=list)
    promoted: bool = False
    measured_at: datetime | None = None
