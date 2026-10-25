#!/bin/sh
set -eu

: "${MIGRATION_DATABASE_URL:?set MIGRATION_DATABASE_URL}"

alembic upgrade head
model-catalog verify --probe-artifacts --json
model-catalog reconcile --mode apply --trigger startup --json
