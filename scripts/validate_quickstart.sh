#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

test -f data/california_housing.parquet
test -f data/dataset-manifest.json
.venv/bin/python -m house_price.data.manifest verify \
  --dataset data/california_housing.parquet \
  --manifest data/dataset-manifest.json
.venv/bin/python scripts/validate_grafana_queries.py
.venv/bin/python - <<'PY'
import json
from pathlib import Path
import yaml
yaml.safe_load(Path("specs/001-train-container-metrics/contracts/openapi.yaml").read_text())
for name in ("champion-manifest.schema.json", "weekly-evidence.schema.json"):
    json.loads((Path("specs/001-train-container-metrics/contracts") / name).read_text())
print("Versioned contracts are syntactically valid")
PY
.venv/bin/pytest -q tests/unit tests/contract

if command -v docker >/dev/null; then
  POSTGRES_PASSWORD=quickstart-postgres \
  MIGRATION_PASSWORD=quickstart-migration \
  PIPELINE_PASSWORD=quickstart-pipeline \
  GRAFANA_PASSWORD=quickstart-grafana \
  DATABASE_URL=postgresql+psycopg://pipeline_writer:quickstart-pipeline@postgres:5432/house_price \
  OPTUNA_STORAGE_URL=postgresql+psycopg://pipeline_writer:quickstart-pipeline@postgres:5432/optuna \
  MLFLOW_BACKEND_STORE_URI=postgresql+psycopg://postgres:quickstart-postgres@postgres:5432/mlflow \
  docker compose config --quiet
fi

echo "Quickstart validation passed; no volumes were removed."

