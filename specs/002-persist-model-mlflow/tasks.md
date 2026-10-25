---

description: "Implementation tasks for persistent model storage and MLflow catalog"
---

# Tasks: Persistência e Catálogo de Modelos

**Input**: Design documents from `/specs/002-persist-model-mlflow/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required by the specification, plan, quickstart acceptance scenarios, and constitutional CI gates. Test tasks appear before the implementation they validate.

**Organization**: Tasks are grouped by user story so persistence, MLflow consultation, and reconciliation can each be implemented and tested as an independent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on an incomplete task
- **[Story]**: Maps the task to User Story 1, 2, or 3
- Every task names the exact file or files it changes

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish configuration, entry points, and durable-storage lifecycle controls shared by every story.

- [X] T001 Add the `model-catalog` console entry point and lock the catalog/runtime dependencies to the same MLflow client/server release in `pyproject.toml` and `uv.lock`
- [X] T002 [P] Add environment-only catalog, recovery-experiment, registered-model, alias, advisory-lock, and persistent-volume settings with secret-safe validation in `src/house_price/settings.py` and `.env.example`
- [X] T003 [P] Create the idempotent `create`, `inspect`, and explicitly confirmed `destroy` workflow for the three stable external volumes in `scripts/manage_persistent_storage.sh`
- [X] T004 Configure stable external `postgres-data`, `mlflow-artifacts`, and `model-registry` volume names while ensuring only MLflow mounts the artifact volume, trainer mounts the registry read-write, and inference mounts it read-only in `compose.yaml`

**Checkpoint**: Configuration and durable storage can be provisioned without implementing catalog behavior.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the schema, contracts, safe filesystem primitives, and MLflow boundary required by all user stories.

**⚠️ CRITICAL**: Complete this phase before starting any user-story implementation.

### Tests for Shared Foundations

- [X] T005 [P] Add JSON Schema tests for the manifest v2, reconciliation report, and deletion-impact examples plus rejection cases in `tests/contract/test_catalog_json_schemas.py`
- [X] T006 [P] Add model-state, uniqueness, transition, UTC timestamp, lowercase SHA-256, and relative-path unit tests in `tests/unit/test_catalog_models.py`
- [X] T007 [P] Add safe-path, symlink, checksum, v1-adapter, complete-v2-package, and validate-before-deserialize tests in `tests/unit/test_registry_atomic.py`
- [X] T008 [P] Add MLflow catalog contract tests for proxy artifact URIs, required run/ModelVersion tags, identity lookup, duplicate detection, public-client APIs, and exact client/server version compatibility in `tests/contract/test_mlflow_catalog.py`
- [X] T009 [P] Add CLI parser, JSON Lines envelope, exit-code 0/2/3/4/5/6/7/8/130, default read-only mode, and secret/path-redaction contract tests in `tests/contract/test_catalog_cli.py`

### Shared Implementation

- [X] T010 Create the `catalog` PostgreSQL schema, enums, tables, indexes, foreign keys, append-only event protection, and uniqueness constraints in `migrations/versions/003_model_catalog.py`
- [X] T011 Implement `model_entries` in `src/house_price/catalog/models.py` with every field rule from `data-model.md`: `model_version` is the stable local PK; `manifest_schema_version` is `1.0.0|2.0.0`; `manifest_sha256` and `model_sha256` are required `char(64)`; `package_relpath` is unique and under `models/`; `training_run_id` is required UUID; source MLflow IDs are nullable original provenance; active MLflow IDs are nullable current links and active version is unique when filled; registered name is `house-price-regressor`; integrity, catalog, lifecycle, and promotion use the documented enums/transitions; diagnostic code is nullable and sanitized; timestamps are UTC; `revision ≥ 1`; active MLflow version requires registered catalog status; and only `verified + registered + active` is promotable
- [X] T012 Implement `reconciliation_runs` and `reconciliation_items` in `src/house_price/catalog/models.py` with every field rule from `data-model.md`: reconciliation UUID is PK; trigger is `manual|startup|weekly|restore`; mode is `check|apply`; fingerprint is `char(64)`; status is `running|succeeded|partial|failed|lock_unavailable`; timestamps are UTC with completion after start; counts are `≥ 0` and registered/recovered/quarantined/unchanged are `0..scanned`; evidence run ID is nullable; transitions are `running → succeeded|partial|failed`; no lock yields `lock_unavailable` without mutation; check mode creates no run/version/alias/tombstone/file; item PK is `(reconciliation_id, package_relpath)` with relative path; identity and checksums are nullable when unreadable; action is `verified|registered|recovered|quarantined|unchanged|conflict`; result is `succeeded|failed|skipped`; reason and MLflow IDs are nullable; occurrence is UTC; and item count exactly equals `scanned_count`
- [X] T013 Implement append-only `operation_events` and `deletion_requests` in `src/house_price/catalog/models.py` with every field rule from `data-model.md`: event UUID is PK; operation UUID correlates the saga; operation is `publish|reconcile|resolve_champion|delete|purge`; model version and before/after snapshots are nullable; phase is stable/resumable; result is `started|succeeded|failed|compensated`; reason is nullable and secret-free; occurrence is UTC; events cannot be updated/deleted; deletion UUID is PK; model version is unique while active; requested/confirmed timestamps are UTC and confirmation requires the exact token; state is `planned|confirmed|trashed|purged|refused|failed`; package is the source; trash path is nullable `.trash/<deletion_id>/<model_version>`; impact records links/aliases/shared references; refusal/failure requires a reason; pointer target, champion alias, last integral model, and active mutation are always refused; trashed is recoverable and purged is irreversible
- [X] T014 Implement transactional catalog CRUD, optimistic revision updates, identity lookup, reconciliation/report persistence, tombstones, and append-only event writes without querying MLflow internal tables in `src/house_price/catalog/repository.py`
- [X] T015 [P] Implement safe relative-path resolution, symlink/escape refusal, streaming SHA-256, temporary-file flush/fsync, atomic `os.replace`, parent-directory fsync, and same-filesystem staging/trash moves in `src/house_price/registry/atomic.py`
- [X] T016 Implement the v2 manifest and v1 read-only adapter in `src/house_price/registry/manifest.py` with every package field rule from `data-model.md`: directory is immutable `models/<model_version>/`; schema is legacy `1.0.0` or current `2.0.0`; model identity is deterministic and equals the directory; business training ID is UUID; source run is original and source version is nullable historical provenance; family is one of `linear|ridge|lasso|decision_tree|random_forest`; code revision, effective parameters, and complete dataset name/version/checksum/schema/row count are required in v2; MAE/MSE/RMSE are non-negative and all metrics finite; signature has the eight canonical inputs and numeric output; artifact paths are relative and checksums cover every file; promotion time is UTC; v2 includes the complete MLflow model directory, `parameters.json`, `metrics.json`, plots, and lockfile; and no symlink, absolute path, or `..` is accepted before deserialization
- [X] T017 Refactor the MLflow boundary to use only public APIs, create `house-price-training-v2` with `mlflow-artifacts:` location, keep legacy experiments read-only, manage `house-price-model-reconciliation`, and distinguish not-found from dependency failures without broad `except Exception` in `src/house_price/tracking/mlflow_client.py`
- [X] T018 Implement the shared non-blocking PostgreSQL advisory-lock context used by publish, reconcile, resolve, delete, and purge operations in `src/house_price/catalog/repository.py`
- [X] T019 Implement the `model-catalog` command tree, environment-only dependency construction, JSON Lines renderer, stable reason codes, redaction, signal handling, and specified exit-code mapping in `src/house_price/catalog/cli.py` and `src/house_price/catalog/__init__.py`
- [X] T020 Add a one-shot MLflow database migration service that backs up before `mlflow db upgrade`, runs the same MLflow release as the server, and gates server startup in `compose.yaml` and `docker/mlflow.Dockerfile`

**Checkpoint**: Schema, contracts, package validation, atomic operations, MLflow access, locking, and CLI infrastructure are ready; story work may now proceed.

---

## Phase 3: User Story 1 — Preservar modelos entre reinicializações (Priority: P1) 🎯 MVP

**Goal**: Publish complete immutable model packages and preserve the approved model, metadata, runs, and artifacts across container restart and recreation without exposing partial publication.

**Independent Test**: Publish models from two runs, record identities, metrics, and checksums, perform five stop/start/recreate cycles without deleting storage, and verify that the same runs, packages, ModelVersions, alias, and loadable champion remain intact; failed writes must leave the previous champion unchanged.

### Tests for User Story 1

- [X] T021 [P] [US1] Add unit fault-injection tests at intent persistence, artifact upload, ModelVersion creation, package materialization, alias preparation, pointer replacement, and final approval to prove retry convergence and compensation in `tests/unit/test_publication_saga.py`
- [X] T022 [P] [US1] Add atomic pointer tests for exclusive temporary files, flush/fsync/replace/directory-fsync ordering, immutable destination collision, and last-known-good preservation in `tests/unit/test_registry_atomic.py`
- [X] T023 [P] [US1] Add storage preflight tests for full, read-only, unavailable, wrong-UID, failed rename, and failed proxy upload/download conditions in `tests/integration/test_storage_permissions.py`
- [X] T024 [P] [US1] Expand the Docker acceptance test to publish two runs, validate all three stores and inference, execute five `down`/`up` cycles plus `--force-recreate`, and assert zero new entities in `tests/integration/test_volume_persistence.py`
- [X] T025 [P] [US1] Add container topology tests proving non-root UIDs, stable external volumes, no client mount of `mlflow-artifacts`, read-only inference registry access, and persistence under ordinary `docker compose down` in `tests/integration/test_container_security.py`
- [X] T026 [P] [US1] Add tests proving inference starts and serves an intact local champion while MLflow/PostgreSQL are unavailable and reports observability degradation separately in `tests/integration/test_inference_catalog_independence.py`

### Implementation for User Story 1

- [X] T027 [US1] Build a v2 immutable package containing the complete MLflow model directory, `parameters.json`, `metrics.json`, plots, `requirements.lock`, dataset/code/environment provenance, signature, and checksums for every file in `src/house_price/training/publishing.py`
- [X] T028 [US1] Publish parameters, MAE/MSE/RMSE/R², lineage, plots, model, manifest, and metadata through the tracking HTTP proxy while rejecting `file:` and absolute artifact locations in `src/house_price/training/tracking.py`
- [X] T029 [US1] Implement the durable publication saga from ledger intent through identity-safe ModelVersion creation/reuse, package materialization, alias preparation, `current.json` commit point, approval, retry, and compensation in `src/house_price/registry/promotion.py`
- [X] T030 [US1] Enforce immutable `models/<model_version>` destinations and write `current.json` using the atomic/fsync primitives while preserving the previous alias and pointer on every pre-commit failure in `src/house_price/registry/pointer.py` and `src/house_price/registry/promotion.py`
- [X] T031 [US1] Add registry and tracking preflight probes for read/write/rename, free space, MLflow health, proxy upload/download cleanup, and artifact-location validation without creating a ModelVersion in `src/house_price/catalog/reconciliation.py`
- [X] T032 [US1] Integrate preflight, v2 packaging, durable saga phases, sanitized structured events, and explicit publication failure into the existing training flow in `src/house_price/training/pipeline.py`
- [X] T033 [US1] Update champion loading to validate pointer, manifest, all checksums, and package identity before deserialization while retaining the already loaded model after catalog outages or invalid reload attempts in `src/house_price/registry/loader.py`
- [X] T034 [US1] Gate trainer startup on successful MLflow migration and catalog preflight while removing MLflow/PostgreSQL startup dependencies from inference in `compose.yaml`

**Checkpoint**: User Story 1 is independently usable as the MVP and proves durable, atomic publication and local serving.

---

## Phase 4: User Story 2 — Consultar modelos no MLflow (Priority: P2)

**Goal**: Make every successfully published model and its origin, quality, lifecycle, and approval state unambiguous through MLflow and read-only catalog commands.

**Independent Test**: Complete one training run and, using only MLflow plus `model-catalog list/verify`, identify within two minutes its family, immutable identity, run, parameters, metrics, dataset, code revision, artifacts, publication state, and champion status; a failed publication remains auditable but is never valid or approved.

### Tests for User Story 2

- [X] T035 [P] [US2] Add an integration test for all required run and ModelVersion tags, artifact layout, parameter/metric equality, unique identity mapping, registered model, and `champion` alias in `tests/integration/test_mlflow_catalog_visibility.py`
- [X] T036 [P] [US2] Add read-only `list` and `verify` integration tests covering filters, all-model and single-version modes, alias/pointer/ledger divergence, proxy checksum verification, JSON Lines completion, and no state mutation in `tests/integration/test_catalog_queries.py`
- [X] T037 [P] [US2] Add a failed-publication audit test proving the failed run and sanitized diagnostic remain visible while no partial ModelVersion becomes `ready` or `approved` in `tests/integration/test_catalog_queries.py`
- [X] T038 [P] [US2] Add the two-minute publication/identification SLO and seeded-secret scan across tags, parameters, textual artifacts, manifests, events, reports, and diagnostics in `tests/performance/test_catalog_visibility_slo.py`

### Implementation for User Story 2

- [X] T039 [US2] Create ModelVersions with initial `catalog.*` identity, manifest/model/dataset checksums, training run, origin, integrity, and publication-state tags; fail on multiple identity matches or checksum conflicts in `src/house_price/tracking/mlflow_client.py`
- [X] T040 [US2] Publish the model under `model/`, manifest and JSON metadata under `metadata/`, plots under `plots/`, complete parameters/metrics, dataset/code references, family, decision, and state in `src/house_price/training/tracking.py`
- [X] T041 [US2] Implement non-deserializing catalog projections and `list` filters for integrity/lifecycle with abbreviated checksums and active MLflow IDs in `src/house_price/catalog/repository.py` and `src/house_price/catalog/cli.py`
- [X] T042 [US2] Implement `verify` for volumes, manifests, ledger, runs, downloadable proxy artifacts, ModelVersions, alias, and pointer, with optional temporary proxy probe cleanup and no ModelVersion creation in `src/house_price/catalog/reconciliation.py` and `src/house_price/catalog/cli.py`
- [X] T043 [US2] Cross-check that a champion is `verified + registered + active`, has one local identity and one active MLflow version, and agrees across package, pointer, ledger, and alias; report divergence without silently repairing it in `src/house_price/catalog/reconciliation.py`

**Checkpoint**: User Story 2 is independently testable through the official MLflow interface and read-only catalog commands.

---

## Phase 5: User Story 3 — Reconciliar modelos existentes (Priority: P3)

**Goal**: Safely discover, verify, register, recover, or quarantine existing packages exactly once without deserialization or implicit promotion.

**Independent Test**: Reconcile at least ten mixed v2, linkable-v1, missing, corrupt, and orphaned packages, then repeat apply five times; every valid model appears exactly once, invalid models remain excluded from serving, and no repeat creates a run, version, association, or semantic event.

### Tests for User Story 3

- [ ] T044 [P] [US3] Add unit classification tests for v2 recovery, linkable v1, unsupported v1, missing metadata/artifact, checksum failure, symlink/path escape, tombstone, duplicate identity, and deterministic scan fingerprint in `tests/unit/test_reconciliation.py`
- [ ] T045 [P] [US3] Add a ten-package integration scenario and five repeated apply passes asserting exact counts, idempotent runs/versions/links/events, quarantine diagnostics, and unchanged champion in `tests/integration/test_catalog_reconciliation.py`
- [ ] T046 [P] [US3] Add restore scenarios for newer volume, newer database/MLflow, missing artifact store, missing/corrupt pointer, divergent alias, and newer tombstone with an old package backup in `tests/integration/test_catalog_restore.py`
- [ ] T047 [P] [US3] Add concurrent publish/reconcile/resolve/delete tests asserting one lock owner, exit code 8 for losers, one identity/version, deterministic final state, and preserved champion in `tests/integration/test_catalog_concurrency.py`

### Implementation for User Story 3

- [ ] T048 [US3] Implement a deterministic scanner limited to `models/<model_version>`, excluding staging/quarantine/trash, refusing symlinks/escapes, and validating schema/files/checksums without deserializing models in `src/house_price/catalog/reconciliation.py`
- [ ] T049 [US3] Implement `reconcile --mode check` as a strictly read-only comparison of package, tombstone, ledger, public MLflow API, alias, and pointer that emits the reconciliation-report contract in `src/house_price/catalog/reconciliation.py` and `src/house_price/catalog/cli.py`
- [ ] T050 [US3] Implement locked `reconcile --mode apply` to reuse one integral identity match, create a missing version only when the original run exists, persist items/events, quarantine invalid or unsupported packages, and never promote discovered content in `src/house_price/catalog/reconciliation.py`
- [ ] T051 [US3] Recover a self-contained v2 package with a missing original run by creating one recovery-experiment run, uploading the full MLflow directory through the proxy, preserving source IDs as tags, and creating exactly one active version in `src/house_price/catalog/reconciliation.py`
- [ ] T052 [US3] Preserve v1 packages through a read-only adapter, link them only when the original run/artifact exists, and otherwise mark them `unsupported` and `quarantined` without deserialization in `src/house_price/catalog/reconciliation.py`
- [ ] T053 [US3] Implement explicit `resolve-champion --prefer volume --apply --confirm VERSION` to repair alias/ledger only toward the intact package already served by `current.json`, with no `--prefer mlflow` path in `src/house_price/catalog/reconciliation.py` and `src/house_price/catalog/cli.py`
- [ ] T054 [US3] Add the one-shot `catalog-reconcile` startup/restore service that applies catalog migrations, verifies all three stores, reconciles before training, and records partial failure as unhealthy in `compose.yaml`

**Checkpoint**: All three user stories are independently functional; reconciliation is safe, idempotent, and never changes serving implicitly.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Complete protected retention, operational automation, quality gates, and documentation spanning multiple stories.

- [ ] T055 [P] Add deletion-impact, protected-target, exact-confirmation, tombstone, atomic trash, idempotent retry, old-backup non-resurrection, and separate irreversible purge tests in `tests/integration/test_catalog_removal.py`
- [ ] T056 Implement dry-run-by-default `delete` and separate `purge`, refuse pointer target, `champion` alias, last integral model, or active mutation, persist impact/tombstone/events, and move packages atomically to `.trash` before MLflow deletion in `src/house_price/catalog/removal.py` and `src/house_price/catalog/cli.py`
- [ ] T057 [P] Add migration upgrade/downgrade, append-only event, catalog-role permission, and schema constraint integration tests in `tests/integration/test_catalog_migration.py`
- [ ] T058 [P] Extend CI with catalog unit/contract/integration tests, migration validation, Docker persistence/security gates, and immutable trainer/inference/MLflow image builds in `.github/workflows/ci.yml`
- [ ] T059 Update the weekly workflow to restore all three logical stores, back up before MLflow/catalog migration, reconcile and verify the champion before training, block unsafe promotion, and archive reports/checksums even when no model is approved in `.github/workflows/weekly-training.yml`
- [ ] T060 [P] Document stable-volume creation/destruction, backup/restore ordering, migration rollback, verify/reconcile/resolve/delete/purge procedures, failure recovery, 10 GiB budget, and future Azure deployment assumptions in `README.md`, `docs/operations.md`, and `docs/azure-deployment-assumptions.md`
- [ ] T061 Execute every scenario and command in `specs/002-persist-model-mlflow/quickstart.md` and record reproducible evidence, timings, counts, checksums, five-cycle results, secret scan, and any environment exceptions in `specs/002-persist-model-mlflow/validation-results.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: No dependencies; begin immediately.
- **Phase 2 — Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3 — User Story 1**: Depends on Phase 2; this is the MVP.
- **Phase 4 — User Story 2**: Depends on Phase 2 and consumes successful publication from US1 for its full end-to-end acceptance test; its query implementation can proceed in parallel with US1.
- **Phase 5 — User Story 3**: Depends on Phase 2 and can use fixtures independently; startup integration into the training path follows US1.
- **Phase 6 — Polish**: Protected removal depends on the foundational ledger and locking; CI, documentation, and final validation follow the desired story phases.

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2 and has no dependency on another story.
- **US2 (P2)**: Query/verification code starts after Phase 2; end-to-end visibility tests consume the publisher delivered by US1.
- **US3 (P3)**: Scanner and reconciliation start after Phase 2 with isolated fixtures; startup workflow integration consumes US1 publication/preflight behavior.

### Within Each User Story

- Write and run the listed tests first; confirm they fail for the intended missing behavior.
- Implement models and storage operations before services and orchestration.
- Implement service behavior before CLI/Compose integration.
- Complete the independent test at the checkpoint before advancing.

---

## Parallel Opportunities

- In Phase 1, T002 and T003 can run in parallel.
- In Phase 2, T005–T009 can run in parallel; T015 can proceed alongside database modeling after its test T007 exists.
- After Phase 2, teams can develop US1 package/publication, US2 query projections, and US3 scanning/classification concurrently using fixtures.
- Within US1, T021–T026 are parallel test files; T027 and T028 can proceed in parallel after shared manifest/MLflow foundations.
- Within US2, T035–T038 are parallel test files; T041 can proceed alongside T039/T040 after repository foundations.
- Within US3, T044–T047 are parallel test files; recovery and v1 handling can be developed from the shared scanner after T048.
- In Phase 6, T055, T057, T058, and T060 touch independent files and can run in parallel.

## Parallel Example: User Story 1

```text
Task T021: Fault-injection saga tests in tests/unit/test_publication_saga.py
Task T023: Storage preflight integration tests in tests/integration/test_storage_permissions.py
Task T024: Five-cycle persistence acceptance test in tests/integration/test_volume_persistence.py
Task T026: Offline-catalog inference test in tests/integration/test_inference_catalog_independence.py
```

## Parallel Example: User Story 2

```text
Task T035: MLflow visibility integration contract in tests/integration/test_mlflow_catalog_visibility.py
Task T036: Read-only catalog query tests in tests/integration/test_catalog_queries.py
Task T038: Visibility SLO and secret scan in tests/performance/test_catalog_visibility_slo.py
```

## Parallel Example: User Story 3

```text
Task T044: Reconciliation classification unit tests in tests/unit/test_reconciliation.py
Task T045: Ten-package idempotency acceptance test in tests/integration/test_catalog_reconciliation.py
Task T046: Restore conflict tests in tests/integration/test_catalog_restore.py
Task T047: Concurrent mutation tests in tests/integration/test_catalog_concurrency.py
```

---

## Implementation Strategy

### MVP First — User Story 1

1. Complete Phase 1 setup.
2. Complete Phase 2 foundations and verify their contract/unit tests.
3. Complete Phase 3 publication, persistence, and inference independence.
4. Stop and run the US1 independent test, including five recreate cycles and failure injection.
5. Demo or review the durable publication MVP before adding catalog query and reconciliation workflows.

### Incremental Delivery

1. **Setup + Foundation** → schema, safe storage, MLflow boundary, and CLI contract are stable.
2. **US1** → publish and serve durable models atomically.
3. **US2** → expose complete, unambiguous model lineage and verification.
4. **US3** → adopt and recover existing models safely and idempotently.
5. **Polish** → protected removal, CI, weekly recovery evidence, and operator documentation.

### Parallel Team Strategy

After Phase 2:

- Developer A owns US1 publication saga and persistence.
- Developer B owns US2 MLflow projections and read-only verification.
- Developer C owns US3 scanning and reconciliation.
- Integrate at the phase checkpoints, then complete Phase 6 together.

---

## Notes

- `[P]` means different files or isolated fixtures with no dependency on an incomplete task.
- User-story labels provide traceability to the specification and are used only in story phases.
- Never deserialize a discovered package during verification or reconciliation.
- Never repair champion divergence or delete model data implicitly.
- Use only public MLflow APIs; do not query its internal tables.
- Preserve the previous intact champion on every failure path.
- Commit after each task or coherent task group and stop at each checkpoint for independent validation.
