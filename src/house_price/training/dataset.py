"""Leakage-safe split, cross-validation, and estimator construction."""

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sklearn.base import RegressorMixin
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.model_selection import KFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

from house_price.domain import FEATURE_NAMES, CandidateFamily


@dataclass(frozen=True)
class DatasetSplit:
    x_train: pd.DataFrame
    x_test: pd.DataFrame
    y_train: pd.Series
    y_test: pd.Series


def deterministic_split(
    frame: pd.DataFrame, *, seed: int = 42, test_fraction: float = 0.33
) -> DatasetSplit:
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between zero and one")
    x = frame.loc[:, FEATURE_NAMES]
    y = frame.loc[:, "MedHouseVal"]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=test_fraction, random_state=seed, shuffle=True
    )
    if set(x_train.index) & set(x_test.index):
        raise RuntimeError("train and test indexes overlap")
    return DatasetSplit(x_train, x_test, y_train, y_test)


def training_folds(seed: int = 42, folds: int = 5) -> KFold:
    if folds < 2:
        raise ValueError("at least two folds are required")
    return KFold(n_splits=folds, shuffle=True, random_state=seed)


def build_estimator(
    family: CandidateFamily, parameters: dict[str, Any] | None = None, *, seed: int = 42
) -> RegressorMixin:
    parameters = parameters or {}
    if family == CandidateFamily.LINEAR:
        estimator: RegressorMixin = LinearRegression(**parameters)
        return Pipeline([("scale", StandardScaler()), ("model", estimator)])
    if family == CandidateFamily.RIDGE:
        estimator = Ridge(random_state=seed, **parameters)
        return Pipeline([("scale", StandardScaler()), ("model", estimator)])
    if family == CandidateFamily.LASSO:
        estimator = Lasso(random_state=seed, max_iter=20_000, **parameters)
        return Pipeline([("scale", StandardScaler()), ("model", estimator)])
    if family == CandidateFamily.DECISION_TREE:
        return DecisionTreeRegressor(random_state=seed, **parameters)
    if family == CandidateFamily.RANDOM_FOREST:
        return RandomForestRegressor(random_state=seed, n_jobs=1, **parameters)
    raise ValueError(f"unsupported model family: {family}")


def unwrap_estimator(estimator: RegressorMixin) -> RegressorMixin:
    if isinstance(estimator, TransformedTargetRegressor):
        return estimator.regressor_
    if isinstance(estimator, Pipeline):
        return estimator.named_steps["model"]
    return estimator
