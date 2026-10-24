---

description: "Dependency-ordered tasks for containerized model training and metrics"
---

# Tasks: Treinamento Conteinerizado com Métricas

**Input**: Design documents from `specs/001-train-container-metrics/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Obrigatórios porque a constituição exige testes unitários, de contrato, integração,
construção das imagens e portões verificáveis antes de merge ou promoção.

**Organization**: As tarefas são agrupadas por história de usuário e incluem IDs de requisitos e
critérios de sucesso para permitir análise automática de cobertura.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Pode executar em paralelo por alterar arquivos distintos e não depender de tarefa aberta.
- **[Story]**: História de usuário atendida (`US1`, `US2`, `US3`).
- Toda tarefa contém caminho exato do arquivo principal alterado.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Inicializar pacote, dependências e imagens básicas da solução.

- [x] T001 Criar `pyproject.toml` para Python 3.12 com MLflow 3.x, Optuna 5.x, scikit-learn 1.9.x, FastAPI, Pydantic, pandas, NumPy, SciPy, psycopg, SQLAlchemy, Alembic, servidor ASGI, pytest, cobertura e ferramentas de lint/formatação
- [x] T002 Gerar `requirements.lock` com versões exatas, hashes e o mesmo conjunto numérico usado por treino e inferência
- [x] T003 Criar o pacote e entrypoints vazios em `src/house_price/__init__.py`, `src/house_price/training/__init__.py`, `src/house_price/api/__init__.py`, `src/house_price/data/__init__.py`, `src/house_price/tracking/__init__.py` e `src/house_price/registry/__init__.py`
- [x] T004 [P] Criar imagem multi-stage não-root do job de treino em `docker/trainer.Dockerfile`, reservando `/app/data` somente leitura e `/model-registry` leitura/escrita
- [x] T005 [P] Criar imagem multi-stage não-root do serviço HTTP em `docker/inference.Dockerfile`, com porta 8000 não privilegiada e `/model-registry` somente leitura
- [x] T006 [P] Criar imagem do Tracking Server com backend e artifact root configuráveis em `docker/mlflow.Dockerfile`
- [x] T007 [P] Documentar todas as variáveis, sem valores secretos, portas e defaults locais seguros em `.env.example`
- [x] T008 Criar esqueleto dos serviços `postgres`, `mlflow`, `trainer` e `inference`, redes internas e volumes `postgres-data`, `mlflow-artifacts`, `model-registry` em `compose.yaml` (covers FR-008)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Infraestrutura compartilhada que bloqueia todas as histórias de usuário.

**⚠️ CRITICAL**: Nenhuma história começa antes desta fase estar completa.

- [x] T009 Implementar configuração tipada por ambiente, rejeição de secrets ausentes e URIs/caminhos sem defaults inseguros em `src/house_price/settings.py`
- [x] T010 [P] Implementar logs JSON correlacionados por `training_run_id`, `mlflow_run_id`, `model_version`, `environment_version`, etapa, família, trial e `request_id`, sem payloads sensíveis, em `src/house_price/logging.py` (covers FR-019)
- [x] T011 Criar bancos/schemas isolados, contas `migration_user`, `pipeline_writer`, `grafana_reader` e privilégios mínimos em `docker/postgres/init.sql`
- [x] T012 Implementar migração de `TrainingRun`, `OptimizationTrial`, `ModelCandidate`, `ArtifactPlot` e `InferenceMetric` em `migrations/versions/001_observability_tables.py`, incluindo IDs únicos, timestamps UTC, métricas finitas, agregados de saúde/volume/erros/p50/p95/p99 sem payloads e constraints de `data-model.md` (covers FR-011, FR-013, FR-019)
- [x] T013 Implementar as views `grafana_model_metric_history`, `grafana_candidate_comparison`, `grafana_training_status`, `grafana_optuna_convergence` e `grafana_inference_operations`, com idade desatualizada após oito dias, em `migrations/versions/002_grafana_views.py` (covers FR-012, FR-013, FR-019, FR-020)
- [x] T014 [P] Implementar enums e modelos compartilhados com famílias `linear`, `ridge`, `lasso`, `decision_tree`, `random_forest` e estados definidos em `data-model.md` em `src/house_price/domain.py`
- [x] T015 [P] Implementar validação do manifesto campeão em `src/house_price/registry/manifest.py`: schema `1.0.0`, UUID, checksums SHA-256, `training_environment_version`, oito inputs `double`, métricas finitas, caminhos sem `..` e versão imutável (covers FR-009, FR-016)
- [x] T016 [P] Implementar cliente MLflow com experimento, Registry `house-price-regressor`, assinatura, tags de código/dataset/família e alias `champion` em `src/house_price/tracking/mlflow_client.py` (covers FR-004, FR-016)
- [x] T017 Implementar repositório SQL transacional e UPSERT idempotente para `training_runs`, `model_metrics`, `optimization_trials` e `artifact_plots` em `src/house_price/tracking/observability.py` (covers FR-011, FR-013, FR-015)
- [x] T018 Completar healthchecks, `depends_on: service_healthy`, dependência PostgreSQL da inferência, mounts RW/RO, publicação PostgreSQL apenas em `127.0.0.1` e execução sem capabilities/socket Docker em `compose.yaml` (covers FR-008, FR-009, FR-019)
- [x] T019 Criar workflow CI inicial com lint, unitários, contratos, integração e build das três imagens como jobs bloqueantes em `.github/workflows/ci.yml`

**Checkpoint**: Fundação pronta; as histórias podem usar fixtures e avançar sem redefinir contratos.

---

## Phase 3: User Story 1 - Treinar e avaliar o modelo (Priority: P1) 🎯 MVP

**Goal**: Validar o snapshot offline, otimizar e avaliar cinco famílias, registrar tudo no MLflow e
promover atomicamente o candidato elegível vencedor.

**Independent Test**: Executar `docker compose run --rm trainer train` sem egress e confirmar cinco
finalistas, MAE/MSE/RMSE/R², decisão rastreável e campeão preservado ou promovido corretamente.

### Tests for User Story 1

> Escrever e confirmar falha destes testes antes da implementação correspondente.

- [x] T020 [P] [US1] Criar testes do `DatasetSnapshot` em `tests/unit/test_dataset_manifest.py`: nome `california_housing`; versão não vazia; SHA-256 com 64 hexadecimais; exatamente 20.640 linhas; oito features na ordem canônica; target `MedHouseVal`; tipos numéricos; rejeição de null, NaN, infinito, duplicidade, coluna extra/ausente e checksum divergente (covers FR-001, FR-002, SC-003, SC-009)
- [x] T021 [P] [US1] Criar testes de split/holdout/folds e promoção: primeira execução usa apenas R² ≥ 0,50; aumentos relativos individuais de MAE e RMSE usam `(novo-anterior)/anterior ≤ 5%`; baseline zero só aceita zero; ranking RMSE → MAE → R² → família em `tests/unit/test_evaluation.py` (covers FR-003, FR-005, FR-006, FR-017, FR-018, SC-002, SC-010, SC-011)
- [x] T022 [P] [US1] Criar testes da hierarquia MLflow pai → família → trial, tags, assinatura, artifacts e alias em `tests/contract/test_mlflow_tracking.py` (covers FR-004, FR-016, SC-001)
- [x] T023 [P] [US1] Criar testes de estudo persistente, nomes determinísticos, `TPESampler(seed=42)`, `n_jobs=1`, retomada e budgets por família em `tests/unit/test_optimization.py` (covers FR-014, FR-017, SC-002)
- [x] T024 [P] [US1] Criar testes do comando, argumentos, JSON Lines e códigos 0/2/3/4/5/6/7/8/130 definidos no contrato em `tests/contract/test_training_cli.py` (covers FR-014, FR-015)
- [x] T025 [P] [US1] Criar teste de integração offline que exige cinco candidatos, mesmos dados/split, quatro métricas, gráficos e conclusão em até 30 minutos em `tests/integration/test_training_pipeline.py` (covers FR-001, FR-005, FR-008, FR-017, SC-001, SC-008, SC-009, SC-010)
- [x] T026 [P] [US1] Criar testes de falha antes/depois de alterar alias, materialização e `current.json`, exigindo compensação do alias, preservação do campeão, staging corrompido e exclusão mútua em `tests/integration/test_promotion_resilience.py` (covers FR-006, FR-007, FR-014, FR-015, FR-018)

### Implementation for User Story 1

- [x] T027 [P] [US1] Implementar geração reproduzível de `data/california_housing.parquet` e `data/dataset-manifest.json` com fonte, versão, schema, 20.640 linhas e SHA-256 em `scripts/build_dataset_snapshot.py` (covers FR-001)
- [x] T028 [P] [US1] Implementar carregamento e todas as validações do snapshot listadas em T020, antes de qualquer split, em `src/house_price/data/validation.py` (covers FR-002, FR-015)
- [x] T029 [P] [US1] Implementar split holdout 33% seed 42, folds somente no treino e pipelines de pré-processamento por família em `src/house_price/training/dataset.py` (covers FR-003, FR-017)
- [x] T030 [P] [US1] Definir e versionar espaços Optuna para Ridge, Lasso, Decision Tree e Random Forest e trial único de Linear Regression em `src/house_price/training/search_spaces.py` (covers FR-017)
- [x] T031 [US1] Implementar `RDBStorage`, estudos `<run>:<family>:<space_version>`, TPESampler seed 42, trials seriais e retomada idempotente em `src/house_price/training/optimization.py` (covers FR-014, FR-017)
- [x] T032 [US1] Implementar MAE/MSE/RMSE/R², primeira promoção apenas com R² ≥ 0,50, aumentos relativos individuais de MAE/RMSE ≤5%, regra de baseline zero e ranking determinístico em `src/house_price/training/evaluation.py` (covers FR-005, FR-006, FR-018)
- [x] T033 [P] [US1] Gerar previsto × observado, resíduos, distribuição de erros, importância/coefs, histórico Optuna e importância de hiperparâmetros em `src/house_price/training/plots.py` (covers FR-004, FR-011)
- [x] T034 [US1] Implementar runs MLflow pai/família/trial, logging de código/dataset/parâmetros/métricas/gráficos e um artifact finalista por família em `src/house_price/training/tracking.py` (covers FR-004, FR-011, FR-017, SC-001)
- [x] T035 [US1] Publicar estado, trials, métricas, promoção e artifacts via UPSERT, bloqueando promoção se a projeção falhar, em `src/house_price/training/publishing.py` (covers FR-011, FR-013, FR-015)
- [x] T036 [US1] Implementar sob advisory lock: deduplicar pela identidade código+dados+split+família+parâmetros+checksum, registrar versão sem alias, materializar/validar staging, mover diretório imutável, alterar alias, trocar `current.json` por `os.replace` e restaurar alias se o ponteiro falhar em `src/house_price/registry/promotion.py` (covers FR-007, FR-014, FR-015, FR-016)
- [x] T037 [US1] Orquestrar estados `pending → validating → optimizing → evaluating → publishing_metrics → promoting → succeeded`, incluindo `failed`, `skipped_concurrent` e `succeeded_no_promotion`, em `src/house_price/training/pipeline.py` (covers FR-007, FR-014, FR-015)
- [x] T038 [US1] Implementar entrypoint `train`, validação de argumentos, retomada e códigos de saída do contrato em `src/house_price/training/cli.py` (covers FR-014, FR-015)
- [x] T039 [US1] Finalizar cópia do snapshot/manifesto, entrypoint, rede sem egress e health de dependências na imagem em `docker/trainer.Dockerfile` (covers FR-001, FR-008, SC-009)
- [x] T040 [US1] Implementar agenda/manual idempotentes em runner hospedado que restauram backup/artifacts anteriores, verificam o snapshot, treinam e publicam por ≥90 dias backup, campeão, logs, métricas e `weekly-evidence.json` válido; primeira execução é tratada explicitamente em `.github/workflows/weekly-training.yml` (covers FR-007, FR-014, FR-015, SC-008)

**Checkpoint**: US1 produz uma decisão auditável e nunca substitui o campeão por resultado inválido.

---

## Phase 4: User Story 2 - Executar o modelo de forma portátil (Priority: P2)

**Goal**: Iniciar inferência local saudável, carregar/recarregar o campeão e responder previsões
validadas com identidade do modelo.

**Independent Test**: Usar um pacote campeão fixture, subir apenas dependências e `inference`, validar
liveness/readiness/model e obter uma previsão; entradas inválidas retornam 422.

### Tests for User Story 2

> Escrever e confirmar falha destes testes antes da implementação correspondente.

- [x] T041 [P] [US2] Validar `contracts/openapi.yaml`, status 200/422/500/503, schemas sem extras e `environment_version` obrigatório em readiness/modelo/predição em `tests/contract/test_openapi.py` (covers FR-009, FR-010)
- [x] T042 [P] [US2] Testar 1..100 instâncias, exatamente oito números finitos, `MedInc/HouseAge/AveBedrms/Population ≥ 0`, `AveRooms/AveOccup > 0`, latitude -90..90, longitude -180..180 e rejeição de extras em `tests/unit/test_api_schemas.py` (covers FR-010)
- [x] T043 [P] [US2] Testar manifesto/checksums, volume read-only, carga inicial, watcher, troca sob lock e manutenção do modelo anterior em erro em `tests/unit/test_model_loader.py` (covers FR-007, FR-009, FR-016)
- [x] T044 [P] [US2] Testar liveness 200, readiness 503 sem campeão, reload válido e correspondência de `environment_version`, `model_version` e run em readiness/modelo/predição em `tests/integration/test_inference_api.py` (covers FR-009, FR-010, FR-016, SC-004)
- [x] T045 [P] [US2] Criar teste de 100 solicitações sequenciais exigindo pelo menos 95% em até 2 segundos em `tests/performance/test_prediction_latency.py` (covers SC-005)

### Implementation for User Story 2

- [x] T046 [P] [US2] Implementar modelos estritos com constraints de T042 e respostas contendo `request_id`, `environment_version`, `model_version` e `mlflow_run_id` em `src/house_price/api/schemas.py` (covers FR-009, FR-010)
- [x] T047 [P] [US2] Implementar leitura de `current.json`, validação do manifesto/pacote MLflow e cache da versão anterior em `src/house_price/registry/loader.py` (covers FR-007, FR-016)
- [x] T048 [US2] Implementar carga no lifespan e watcher de `current.json` com troca atômica da referência em memória em `src/house_price/api/model_service.py` (covers FR-007, FR-009)
- [x] T049 [US2] Implementar endpoints OpenAPI e reportar a revisão imutável da imagem como `environment_version` em `src/house_price/api/routes.py` (covers FR-009, FR-010)
- [x] T050 [US2] Montar FastAPI, handlers 422/500/503, logs correlacionados e heartbeat/agregação por minuto de saúde, volume, erros e p50/p95/p99 no PostgreSQL em `src/house_price/api/app.py` (covers FR-009, FR-010, FR-015, FR-019)
- [x] T051 [US2] Finalizar servidor não-root, healthcheck `/health/ready`, volume `model-registry:ro` e porta 8000 em `docker/inference.Dockerfile` e `compose.yaml` (covers FR-008, FR-009, SC-004)
- [x] T052 [US2] Criar pacote campeão fixture completo e válido para testes independentes de US1 em `tests/fixtures/model-registry/models/fixture-v1/manifest.json` e `tests/fixtures/model-registry/models/fixture-v1/model/MLmodel`

**Checkpoint**: US2 funciona com fixture e, integrada à US1, recarrega o campeão sem indisponibilidade.

---

## Phase 5: User Story 3 - Acompanhar qualidade da regressão (Priority: P3)

**Goal**: Permitir que Grafana externo consulte histórico, compare candidatos e diferencie promoção,
rejeição, falha e dado desatualizado sem acessar schemas internos.

**Independent Test**: Carregar fixtures de cinco execuções, conectar como `grafana_reader`, executar
todas as queries/alertas e identificar melhor/pior execução e campeão em até dois minutos.

### Tests for User Story 3

> Escrever e confirmar falha destes testes antes da implementação correspondente.

- [x] T053 [P] [US3] Criar fixtures SQL com cinco execuções, cinco candidatos cada, janelas de inferência, promoção, rejeição e falha em `tests/fixtures/observability_runs.sql` (covers SC-007)
- [x] T054 [P] [US3] Testar cinco views, UPSERT idempotente, métricas de saúde/volume/erros/latência e `grafana_reader` limitado a `USAGE/SELECT` em `tests/contract/test_observability_sql.py` (covers FR-011, FR-012, FR-013, FR-019, SC-006)
- [x] T055 [P] [US3] Validar datasource, MAE/MSE/RMSE/R², cinco execuções, painéis operacionais e alertas de falha semanal/indisponibilidade/qualidade em `tests/contract/test_grafana_dashboard.py` (covers FR-012, FR-013, FR-019, FR-020, SC-006, SC-007, SC-012)
- [x] T056 [P] [US3] Testar persistência após falha, idade >8 dias, Grafana indisponível sem perda e estado de alerta visível ≤5 minutos em `tests/integration/test_metrics_persistence.py` (covers FR-013, FR-020, SC-012)

### Implementation for User Story 3

- [x] T057 [P] [US3] Criar datasource PostgreSQL externo parametrizado, usuário read-only e sem secrets versionados em `grafana/datasource.example.yaml` (covers FR-012)
- [x] T058 [US3] Implementar dashboard com MAE/MSE/RMSE/R², comparação de cinco execuções, convergência, saúde, volume, erros, p50/p95/p99 e idade >8 dias em `grafana/dashboards/house-price-ml.json`, e alertas incluindo `No Data`/heartbeat >5 minutos em `grafana/alerts/house-price-alerts.yaml` (covers FR-012, FR-013, FR-019, FR-020, SC-006, SC-007, SC-012)
- [x] T059 [US3] Implementar validador das queries, permissões e regras de alerta usadas pelo Grafana em `scripts/validate_grafana_queries.py` (covers FR-012, FR-020, SC-006, SC-012)

**Checkpoint**: US3 funciona somente com PostgreSQL + fixtures e integra-se à US1 sem consultar MLflow internamente.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validar requisitos que atravessam as três histórias e preparar uso seguro.

- [x] T060 [P] Criar teste de repetição cinco vezes com tolerância absoluta `1e-9`, mesma decisão e métricas em `tests/integration/test_reproducibility.py` (covers SC-002, SC-009, SC-011)
- [x] T061 [P] Criar teste de persistência após `docker compose down/up`, preservando runs, métricas, artifacts e `model_version`, em `tests/integration/test_volume_persistence.py` (covers FR-007, FR-013, SC-004)
- [x] T062 [P] Criar teste de segurança para UID não-root, revisão OCI imutável, ausência de capabilities/socket Docker, volume RO, secrets e dados sensíveis fora de imagem/logs em `tests/integration/test_container_security.py` (covers FR-008, FR-009)
- [x] T063 Criar benchmark em host de referência com 4 CPUs, 8 GiB RAM, 10 GiB livres e caches previamente aquecidos para startup ≤10 min, treino ≤30 min, métricas/alertas ≤5 min, predição conforme SC-005 e envelope CPU/memória/disco por serviço em `tests/performance/test_end_to_end_slo.py` (covers SC-004, SC-005, SC-006, SC-008, SC-012)
- [x] T064 Implementar backup/restore e premissas Azure com custo desta feature US$0, envelope de recursos, portas, secrets, persistência, cotas futuras e rollback em `docs/operations.md` e `docs/azure-deployment-assumptions.md` (covers FR-007, FR-013)
- [x] T065 Atualizar instalação, treino, MLflow, inferência, Grafana externo, persistência, troubleshooting e limites locais em `README.md`
- [x] T066 Automatizar os cenários de `quickstart.md` sem remover volumes em `scripts/validate_quickstart.sh`
- [x] T067 Completar CI com lockfile, migrações, OpenAPI, ambos JSON Schemas, dashboard/alertas, imagens, segurança, integração e benchmarks bloqueantes em `.github/workflows/ci.yml`
- [ ] T068 Executar validação completa, incluindo inferência sobre o campeão, readiness, previsão e rollback após US2, e registrar versões, tempos, recursos, alertas, evidência semanal e resultados dos portões em `specs/001-train-container-metrics/validation-results.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: sem dependências.
- **Phase 2 — Foundational**: depende da Phase 1 e bloqueia todas as histórias.
- **Phase 3 — US1**: depende da Phase 2; constitui o MVP.
- **Phase 4 — US2**: depende da Phase 2 e usa fixture própria; integração real usa o campeão da US1.
- **Phase 5 — US3**: depende da Phase 2 e usa fixtures SQL; integração real usa projeções da US1.
- **Phase 6 — Polish**: depende das histórias selecionadas; T063, T066–T068 exigem US1+US2+US3.

### User Story Dependencies

```text
Setup → Foundation ┬→ US1 (MVP: treino e campeão)
                   ├→ US2 (inferência com fixture)
                   └→ US3 (Grafana com fixtures)

US1 + US2 + US3 → validação ponta a ponta
```

- **US1** não depende de US2/US3 para produzir e auditar o campeão.
- **US2** é testável sem US1 usando `tests/fixtures/model-registry/`.
- **US3** é testável sem US1 usando `tests/fixtures/observability_runs.sql`.
- A demonstração integrada segue US1 → US2 → US3.

### Within Each User Story

- Escrever testes e confirmar falha antes da implementação correspondente.
- Modelos/constraints antes de serviços; serviços antes de entrypoints/endpoints.
- Persistir MLflow e observabilidade antes de promover.
- Validar staging antes de trocar `current.json`.
- Concluir o checkpoint da história antes de considerá-la pronta.

### Parallel Opportunities

- T004–T007 podem avançar em paralelo após T001–T003.
- T010, T014–T016 podem avançar em paralelo enquanto o schema base é preparado.
- Testes T020–T026 são paralelizáveis por arquivo; implementação T027–T030 e T033 também.
- Testes T041–T045 e implementações T046–T047 podem avançar em paralelo.
- T053–T057 podem avançar em paralelo após as migrações fundamentais.
- T060–T062 podem avançar em paralelo após as histórias correspondentes.

---

## Parallel Example: User Story 1

```text
T020 Dataset manifest tests
T021 Evaluation and ranking tests
T022 MLflow contract tests
T023 Optuna persistence tests
T024 Training CLI contract tests
T025 Offline pipeline integration test
T026 Promotion resilience test
```

## Parallel Example: User Story 2

```text
T041 OpenAPI contract test
T042 Request constraint tests
T043 Champion loader tests
T044 Inference integration test
T045 Prediction latency test
```

## Parallel Example: User Story 3

```text
T053 Observability fixtures
T054 SQL contract and permissions test
T055 Grafana dashboard contract test
T056 Metrics persistence test
T057 External datasource example
```

---

## Implementation Strategy

### MVP First — User Story 1

1. Concluir Phase 1 e Phase 2.
2. Escrever os testes T020–T026 e confirmar que falham.
3. Implementar T027–T040.
4. Validar treino offline, cinco finalistas, gates e promoção atômica.
5. Parar e demonstrar o MLflow e o volume campeão antes de ampliar o escopo.

### Incremental Delivery

1. **Fundação**: Compose, PostgreSQL, tracking, schemas e CI.
2. **US1**: pipeline treinável e campeão auditável — MVP.
3. **US2**: inferência portátil e contrato HTTP.
4. **US3**: dashboard externo e histórico operacional.
5. **Polish**: resiliência, desempenho, segurança, documentação e validação completa.

### Parallel Team Strategy

Após Foundation:

- Pessoa A executa US1.
- Pessoa B executa US2 contra o pacote fixture.
- Pessoa C executa US3 contra fixtures SQL.
- Integração final substitui fixtures pelos outputs reais sem mudar contratos.

## Notes

- `[P]` só aparece onde arquivos e dependências permitem execução paralela.
- `[US1]`, `[US2]` e `[US3]` fornecem rastreabilidade para histórias e requisitos.
- Commits devem agrupar uma tarefa ou um conjunto lógico pequeno.
- Não executar `docker compose down -v` nos testes normais.
- Não consultar schemas internos de MLflow/Optuna pelo Grafana.
- Azure permanece fora do escopo desta feature.
