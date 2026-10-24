"""Environment-only configuration for training and inference."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    database_url: str = Field(min_length=1)
    optuna_storage_url: str = Field(min_length=1)
    mlflow_tracking_uri: str = Field(min_length=1)
    model_registry_path: Path = Path("/model-registry")
    dataset_path: Path = Path("/app/data/california_housing.parquet")
    dataset_manifest_path: Path = Path("/app/data/dataset-manifest.json")
    environment_version: str = Field(default="local-dev", min_length=1)
    training_environment_version: str = Field(default="local-dev", min_length=1)
    code_revision: str = Field(default="local-dev", min_length=1)
    log_level: str = "INFO"
    pipeline_password: SecretStr | None = None

    @field_validator("database_url", "optuna_storage_url")
    @classmethod
    def reject_unsafe_database_url(cls, value: str) -> str:
        if "changeme" in value.lower():
            raise ValueError("database URLs must not contain placeholder credentials")
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("only PostgreSQL URLs are supported")
        return value

    @field_validator("mlflow_tracking_uri")
    @classmethod
    def validate_tracking_uri(cls, value: str) -> str:
        if not value.startswith(("http://", "https://", "file:")):
            raise ValueError("unsupported MLflow tracking URI")
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
