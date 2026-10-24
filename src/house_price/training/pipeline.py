"""End-to-end deterministic training, tracking, evaluation, and promotion."""

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

import joblib
import mlflow
from sqlalchemy import create_engine

from house_price.data.validation import DatasetSnapshot, load_and_validate_snapshot
from house_price.domain import CandidateFamily, ModelCandidate, ModelMetrics, TrainingStatus
from house_price.registry.manifest import sha256_file
from house_price.registry.promotion import (
    ConcurrentPromotionError,
    PromotionError,
    PromotionManager,
    prepare_staging,
    result_identity,
)
from house_price.settings import Settings
from house_price.tracking.mlflow_client import TrackingClient
from house_price.tracking.observability import ObservabilityRepository
from house_price.training.dataset import build_estimator, deterministic_split, unwrap_estimator
from house_price.training.evaluation import apply_gate, regression_metrics, select_winner
from house_price.training.optimization import optimize_family
from house_price.training.plots import evaluation_plots, optimization_history, parameter_importance
from house_price.training.publishing import TrainingPublisher
from house_price.training.search_spaces import DEFAULT_TRIAL_BUDGETS
from house_price.training.tracking import TrainingTracker

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineOptions:
    run_id: str
    seed: int = 42
    test_fraction: float = 0.33
    cv_folds: int = 5
    timeout_seconds: int = 1_700
    trial_budgets: dict[CandidateFamily, int] | None = None
    resume: bool = False


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    status: TrainingStatus
    candidates: tuple[ModelCandidate, ...]
    promoted: bool
    model_version: str | None
    duration_seconds: float


def _champion_metrics(registry_root: Path) -> ModelMetrics | None:
    pointer_path = registry_root / "current.json"
    if not pointer_path.is_file():
        return None
    pointer = json.loads(pointer_path.read_text())
    manifest = json.loads((registry_root / pointer["manifest_path"]).read_text())
    return ModelMetrics(**manifest["metrics"])


def _run_values(
    options: PipelineOptions,
    snapshot: DatasetSnapshot,
    parent_run_id: str,
    code_revision: str,
    started_at: datetime,
) -> dict[str, object]:
    return {
        "training_run_id": options.run_id,
        "mlflow_parent_run_id": parent_run_id,
        "dataset_version": snapshot.dataset_version,
        "dataset_checksum": snapshot.sha256,
        "code_revision": code_revision,
        "started_at": started_at,
        "completed_at": None,
        "status": TrainingStatus.PENDING.value,
        "failure_stage": None,
        "promoted_model_version": None,
    }


def _build_package(
    *,
    root: Path,
    winner: ModelCandidate,
    estimator: object,
    plots: list[Path],
    snapshot: DatasetSnapshot,
    settings: Settings,
    options: PipelineOptions,
    mlflow_model_version: str,
) -> tuple[Path, str]:
    build_root = root / ".package-build"
    build_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="champion-", dir=build_root))
    model_dir = temporary / "model"
    model_dir.mkdir()
    model_file = model_dir / "model.joblib"
    joblib.dump(estimator, model_file)
    model_checksum = sha256_file(model_file)
    model_version = result_identity(
        code_revision=settings.code_revision,
        dataset_checksum=snapshot.sha256,
        split_seed=options.seed,
        test_fraction=options.test_fraction,
        family=winner.family.value,
        parameters=winner.parameters,
        model_checksum=model_checksum,
    )[:24]
    plot_dir = temporary / "plots"
    plot_dir.mkdir()
    plot_paths: list[str] = []
    for plot in plots:
        destination = plot_dir / plot.name
        shutil.copy2(plot, destination)
        plot_paths.append(f"plots/{plot.name}")
    metrics = winner.metrics.__dict__
    (temporary / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True) + "\n", encoding="utf-8"
    )
    lock_path = Path("/app/requirements.lock")
    if not lock_path.is_file():
        lock_path = Path("requirements.lock")
    previous = None
    pointer = root / "current.json"
    if pointer.is_file():
        previous = json.loads(pointer.read_text()).get("model_version")
    manifest = {
        "schema_version": "1.0.0",
        "model_version": model_version,
        "registered_model_name": "house-price-regressor",
        "mlflow_model_version": mlflow_model_version,
        "mlflow_run_id": winner.mlflow_run_id,
        "training_run_id": winner.training_run_id,
        "candidate_family": winner.family.value,
        "dataset": {
            "name": snapshot.dataset_name,
            "version": snapshot.dataset_version,
            "sha256": snapshot.sha256,
            "row_count": snapshot.row_count,
            "schema_version": snapshot.schema_version,
        },
        "model_checksum": model_checksum,
        "dependency_lock_checksum": sha256_file(lock_path),
        "training_environment_version": settings.training_environment_version,
        "metrics": metrics,
        "signature": {
            "inputs": [{"name": name, "type": "double"} for name in snapshot.feature_names],
            "output": "double",
        },
        "artifacts": {
            "model_path": "model",
            "metrics_path": "metrics.json",
            "plots": plot_paths,
        },
        "promoted_at": datetime.now(UTC).isoformat(),
        "previous_model_version": previous,
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return temporary, model_version


def run_pipeline(settings: Settings, options: PipelineOptions) -> PipelineResult:
    started_clock = monotonic()
    started_at = datetime.now(UTC)
    frame, snapshot = load_and_validate_snapshot(
        settings.dataset_path, settings.dataset_manifest_path
    )
    split = deterministic_split(frame, seed=options.seed, test_fraction=options.test_fraction)
    tracking_client = TrackingClient(settings.mlflow_tracking_uri)
    tracker = TrainingTracker(tracking_client)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    publisher = TrainingPublisher(ObservabilityRepository(engine=engine))
    champion_metrics = _champion_metrics(settings.model_registry_path)
    candidates: list[ModelCandidate] = []
    fitted: dict[CandidateFamily, object] = {}
    candidate_plots: dict[CandidateFamily, list[Path]] = {}
    parent_tags = {
        "training_run_id": options.run_id,
        "code_revision": settings.code_revision,
        "dataset_version": snapshot.dataset_version,
        "dataset_checksum": snapshot.sha256,
    }
    run_values: dict[str, object] | None = None
    stage = TrainingStatus.VALIDATING.value

    try:
        with tracker.parent_run(options.run_id, parent_tags) as parent_run_id:
            run_values = _run_values(
                options, snapshot, parent_run_id, settings.code_revision, started_at
            )
            publisher.publish_run(**run_values)
            stage = TrainingStatus.VALIDATING.value
            publisher.publish_run(**{**run_values, "status": stage})
            stage = TrainingStatus.OPTIMIZING.value
            publisher.publish_run(**{**run_values, "status": stage})
            budgets = {**DEFAULT_TRIAL_BUDGETS, **(options.trial_budgets or {})}
            per_family_timeout = max(1, options.timeout_seconds // len(CandidateFamily))
            with tempfile.TemporaryDirectory(prefix="house-price-plots-") as plot_root:
                for family in CandidateFamily:
                    family_tags = {**parent_tags, "candidate_family": family.value}
                    with tracker.family_run(family.value, family_tags) as family_run_id:
                        optimization = optimize_family(
                            options.run_id,
                            family,
                            split.x_train,
                            split.y_train,
                            storage_url=settings.optuna_storage_url,
                            trial_budget=budgets[family],
                            seed=options.seed,
                            folds=options.cv_folds,
                            timeout=per_family_timeout,
                        )
                        for trial in optimization.study.trials:
                            if trial.value is None:
                                continue
                            with tracker.trial_run(
                                family.value, trial.number, trial.params
                            ) as trial_run_id:
                                mlflow.log_metric("cv_rmse_mean", float(trial.value))
                            publisher.publish_trial(
                                training_run_id=options.run_id,
                                candidate_family=family.value,
                                study_name=optimization.study_name,
                                trial=trial,
                                mlflow_run_id=trial_run_id,
                            )
                        estimator = build_estimator(
                            family, optimization.parameters, seed=options.seed
                        )
                        estimator.fit(split.x_train, split.y_train)
                        prediction = estimator.predict(split.x_test)
                        metrics = regression_metrics(split.y_test, prediction)
                        family_plot_dir = Path(plot_root) / family.value
                        plots = evaluation_plots(
                            split.y_test.to_numpy(),
                            prediction,
                            family_plot_dir,
                            feature_names=snapshot.feature_names,
                            estimator=unwrap_estimator(estimator),
                        )
                        plots.append(optimization_history(optimization.study, family_plot_dir))
                        plots.append(parameter_importance(optimization.study, family_plot_dir))
                        tracker.log_finalist(
                            estimator,
                            metrics,
                            optimization.parameters,
                            plots,
                            input_example=split.x_train.head(3),
                        )
                        candidate = apply_gate(
                            ModelCandidate(
                                training_run_id=options.run_id,
                                family=family,
                                mlflow_run_id=family_run_id,
                                best_trial_number=optimization.best_trial_number,
                                parameters=optimization.parameters,
                                metrics=metrics,
                                artifact_uri=f"runs:/{family_run_id}/model",
                                measured_at=datetime.now(UTC),
                            ),
                            champion_metrics,
                        )
                        candidates.append(candidate)
                        fitted[family] = estimator
                        candidate_plots[family] = plots
                        for plot in plots:
                            publisher.publish_plot(
                                training_run_id=options.run_id,
                                candidate_family=family.value,
                                mlflow_run_id=family_run_id,
                                plot=plot,
                            )

                stage = TrainingStatus.EVALUATING.value
                publisher.publish_run(**{**run_values, "status": stage})
                stage = TrainingStatus.PUBLISHING_METRICS.value
                publisher.publish_run(**{**run_values, "status": stage})
                for candidate in candidates:
                    publisher.publish_candidate(candidate)
                winner = select_winner(candidates)
                if winner is None:
                    completed = datetime.now(UTC)
                    publisher.publish_run(
                        **{
                            **run_values,
                            "status": TrainingStatus.SUCCEEDED_NO_PROMOTION.value,
                            "completed_at": completed,
                        }
                    )
                    return PipelineResult(
                        options.run_id,
                        TrainingStatus.SUCCEEDED_NO_PROMOTION,
                        tuple(candidates),
                        False,
                        None,
                        monotonic() - started_clock,
                    )

                stage = TrainingStatus.PROMOTING.value
                publisher.publish_run(**{**run_values, "status": stage})
                package, proposed_version = _build_package(
                    root=settings.model_registry_path,
                    winner=winner,
                    estimator=fitted[winner.family],
                    plots=candidate_plots[winner.family],
                    snapshot=snapshot,
                    settings=settings,
                    options=options,
                    mlflow_model_version="pending",
                )
                manager = PromotionManager(
                    settings.model_registry_path, tracking_client, lock_engine=engine
                )
                with manager.lock():
                    current_pointer = manager.current_pointer()
                    if current_pointer and current_pointer.get("model_version") == proposed_version:
                        shutil.rmtree(package)
                        publisher.publish_run(
                            **{
                                **run_values,
                                "status": TrainingStatus.SUCCEEDED_NO_PROMOTION.value,
                                "completed_at": datetime.now(UTC),
                            }
                        )
                        return PipelineResult(
                            options.run_id,
                            TrainingStatus.SUCCEEDED_NO_PROMOTION,
                            tuple(candidates),
                            False,
                            proposed_version,
                            monotonic() - started_clock,
                        )
                    try:
                        mlflow_version = tracking_client.register_without_alias(
                            winner.artifact_uri, winner.mlflow_run_id
                        )
                        manifest_path = package / "manifest.json"
                        manifest_data = json.loads(manifest_path.read_text())
                        manifest_data["mlflow_model_version"] = mlflow_version
                        manifest_path.write_text(
                            json.dumps(manifest_data, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        staging = prepare_staging(
                            package, settings.model_registry_path, proposed_version
                        )
                        shutil.rmtree(package)
                        model_version, promoted = manager.promote_locked(
                            staging, mlflow_version=mlflow_version
                        )
                    except Exception as exc:
                        raise PromotionError("candidate promotion failed") from exc
                winner.promoted = promoted
                publisher.publish_candidate(winner)
                status = (
                    TrainingStatus.SUCCEEDED if promoted else TrainingStatus.SUCCEEDED_NO_PROMOTION
                )
                publisher.publish_run(
                    **{
                        **run_values,
                        "status": status.value,
                        "completed_at": datetime.now(UTC),
                        "promoted_model_version": model_version if promoted else None,
                    }
                )
                return PipelineResult(
                    options.run_id,
                    status,
                    tuple(candidates),
                    promoted,
                    model_version,
                    monotonic() - started_clock,
                )
    except ConcurrentPromotionError:
        LOGGER.warning("concurrent promotion skipped", extra={"stage": stage})
        if run_values is not None:
            publisher.publish_run(
                **{
                    **run_values,
                    "status": TrainingStatus.SKIPPED_CONCURRENT.value,
                    "completed_at": datetime.now(UTC),
                }
            )
        raise
    except Exception:
        LOGGER.exception("training pipeline failed", extra={"stage": stage})
        if run_values is not None:
            try:
                publisher.publish_failure(run_values, stage)
            except Exception:
                LOGGER.exception("failed to publish pipeline failure", extra={"stage": stage})
        raise


def new_options() -> PipelineOptions:
    return PipelineOptions(run_id=str(uuid4()))
