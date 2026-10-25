#!/usr/bin/env bash
set -euo pipefail

readonly POSTGRES_VOLUME_NAME="${POSTGRES_VOLUME_NAME:-house-price-postgres-data}"
readonly MLFLOW_ARTIFACTS_VOLUME_NAME="${MLFLOW_ARTIFACTS_VOLUME_NAME:-house-price-mlflow-artifacts}"
readonly MODEL_REGISTRY_VOLUME_NAME="${MODEL_REGISTRY_VOLUME_NAME:-house-price-model-registry}"
readonly VOLUMES=(
  "$POSTGRES_VOLUME_NAME"
  "$MLFLOW_ARTIFACTS_VOLUME_NAME"
  "$MODEL_REGISTRY_VOLUME_NAME"
)

usage() {
  echo "usage: $0 create|inspect|destroy [--confirm destroy]" >&2
}

validate_name() {
  local value="$1"
  if [[ ! "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
    echo "refusing unsafe Docker volume name: $value" >&2
    exit 2
  fi
}

for volume in "${VOLUMES[@]}"; do
  validate_name "$volume"
done

command_name="${1:-}"
case "$command_name" in
  create)
    for volume in "${VOLUMES[@]}"; do
      if ! docker volume inspect "$volume" >/dev/null 2>&1; then
        docker volume create --label house-price.persistence=managed "$volume" >/dev/null
      fi
      echo "$volume"
    done
    ;;
  inspect)
    docker volume inspect "${VOLUMES[@]}"
    ;;
  destroy)
    if [[ "${2:-}" != "--confirm" || "${3:-}" != "destroy" ]]; then
      echo "destruction requires: $0 destroy --confirm destroy" >&2
      exit 2
    fi
    for volume in "${VOLUMES[@]}"; do
      if docker volume inspect "$volume" >/dev/null 2>&1; then
        managed="$(docker volume inspect --format '{{ index .Labels "house-price.persistence" }}' "$volume")"
        if [[ "$managed" != "managed" ]]; then
          echo "refusing to remove unmanaged volume: $volume" >&2
          exit 3
        fi
      fi
    done
    for volume in "${VOLUMES[@]}"; do
      if docker volume inspect "$volume" >/dev/null 2>&1; then
        docker volume rm "$volume"
      fi
    done
    ;;
  *)
    usage
    exit 2
    ;;
esac
