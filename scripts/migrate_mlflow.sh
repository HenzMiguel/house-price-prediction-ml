#!/usr/bin/env bash
set -euo pipefail

backend_uri="${MLFLOW_BACKEND_STORE_URI:?set MLFLOW_BACKEND_STORE_URI}"
backup_dir="${MLFLOW_MIGRATION_BACKUP_DIR:-/backup}"
mkdir -p "$backup_dir"
if [[ ! -w "$backup_dir" ]]; then
  echo "MLflow migration backup directory is not writable" >&2
  exit 6
fi

postgres_uri="${backend_uri/postgresql+psycopg:/postgresql:}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="$backup_dir/mlflow-before-upgrade-$timestamp.dump"
umask 077
pg_dump --format=custom --file "$backup_path" "$postgres_uri"
test -s "$backup_path"
sha256sum "$backup_path" > "$backup_path.sha256"
mlflow db upgrade "$backend_uri"
