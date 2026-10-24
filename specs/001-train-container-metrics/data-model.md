# Data Model: Treinamento Conteinerizado com Métricas

## Visão geral

O PostgreSQL mantém três domínios logicamente isolados: metadados administrados pelo MLflow,
estudos administrados pelo Optuna e projeções próprias em `observability`. Artefatos grandes ficam em
volumes Docker. IDs são strings imutáveis; timestamps usam UTC; métricas usam ponto flutuante finito.

## DatasetSnapshot

Representa os dados imutáveis incluídos na imagem de treinamento.

| Campo | Tipo | Regra |
|---|---|---|
| `dataset_name` | string | constante `california_housing` |
| `dataset_version` | string | versão não vazia e imutável |
| `source_uri` | string | origem documentada do snapshot |
| `sha256` | string | 64 caracteres hexadecimais |
| `row_count` | integer | exatamente 20.640 nesta versão |
| `feature_names` | string[8] | ordem canônica das oito features |
| `target_name` | string | constante `MedHouseVal` |
| `created_at` | datetime | UTC |
| `schema_version` | string | versão do contrato de dados |

Validações: arquivo e manifesto devem concordar; nenhuma feature/target pode conter `null`, `NaN` ou
infinito; todas as colunas são numéricas; colunas extras, ausentes ou fora de ordem invalidam o
snapshot; checksum divergente encerra a execução antes do split.

## TrainingRun

Execução ponta a ponta, correspondente a uma run pai MLflow e uma linha
`observability.training_runs`.

| Campo | Tipo | Regra |
|---|---|---|
| `training_run_id` | UUID | chave primária idempotente |
| `mlflow_parent_run_id` | string | único, obrigatório após início do tracking |
| `dataset_version` | string | referência a `DatasetSnapshot` |
| `dataset_checksum` | string | deve coincidir com o snapshot validado |
| `code_revision` | string | commit SHA ou identificador imutável |
| `split_seed` | integer | 42 |
| `test_fraction` | decimal | 0,33 |
| `started_at` | datetime | UTC |
| `completed_at` | datetime/null | posterior a `started_at` |
| `status` | enum | transições abaixo |
| `failure_stage` | string/null | obrigatório quando `failed` |
| `promoted_model_version` | string/null | definido somente após promoção |

Estados: `pending → validating → optimizing → evaluating → publishing_metrics → promoting →
succeeded`. Qualquer estado ativo pode ir para `failed`. Uma execução sem lock vai de `pending` para
`skipped_concurrent`. Uma execução sem candidato elegível termina `succeeded_no_promotion` após
publicar métricas.

## OptimizationStudy

Estudo Optuna persistente por família dentro de uma execução.

| Campo | Tipo | Regra |
|---|---|---|
| `study_name` | string | único: `<training_run_id>:<family>:<space_version>` |
| `training_run_id` | UUID | referência a `TrainingRun` |
| `candidate_family` | enum | `linear`, `ridge`, `lasso`, `decision_tree`, `random_forest` |
| `space_version` | string | identifica limites dos hiperparâmetros |
| `sampler` | string | `TPESampler` ou baseline determinístico |
| `seed` | integer | 42 |
| `direction` | enum | `minimize` |
| `objective_name` | string | `cv_rmse_mean` |
| `trial_budget` | integer | positivo; limitado pelo timeout global |
| `best_trial_number` | integer/null | definido após estudo concluído |

## OptimizationTrial

Projeção observável de um trial; o registro completo permanece no Optuna e no MLflow.

| Campo | Tipo | Regra |
|---|---|---|
| `study_name` | string | parte da chave composta |
| `trial_number` | integer | parte da chave composta, não negativo |
| `training_run_id` | UUID | correlação da pipeline |
| `candidate_family` | enum | mesma família do estudo |
| `mlflow_run_id` | string | único |
| `parameters` | JSON object | somente valores serializáveis |
| `objective_rmse` | float/null | finito quando `complete` |
| `state` | enum | `running`, `complete`, `pruned`, `failed` |
| `duration_seconds` | float/null | não negativo |
| `completed_at` | datetime/null | UTC |

Unicidade: `(study_name, trial_number)`. UPSERT repetido com os mesmos valores é idempotente.

## ModelCandidate

Melhor trial de uma família, avaliado no holdout comum.

| Campo | Tipo | Regra |
|---|---|---|
| `training_run_id` | UUID | parte da chave composta |
| `candidate_family` | enum | parte da chave composta |
| `mlflow_run_id` | string | run filha do finalista |
| `best_trial_number` | integer | trial vencedor da família |
| `parameters` | JSON object | hiperparâmetros efetivos |
| `mae` | float | finito, ≥ 0 |
| `mse` | float | finito, ≥ 0 |
| `rmse` | float | finito, ≥ 0 e compatível com `sqrt(mse)` |
| `r2` | float | finito |
| `eligible` | boolean | calculado pelos gates |
| `ineligibility_reasons` | string[] | vazio quando elegível |
| `promoted` | boolean | somente um por execução |
| `measured_at` | datetime | UTC |
| `artifact_uri` | string | pacote MLflow do finalista |

Unicidade: `(training_run_id, candidate_family)`. Ordenação do campeão: RMSE crescente, MAE
crescente, R² decrescente e ordem `linear`, `ridge`, `lasso`, `decision_tree`, `random_forest`.

## ChampionModel

Versão promovida, registrada no MLflow e materializada em `model-registry`.

| Campo | Tipo | Regra |
|---|---|---|
| `model_version` | string | único e imutável |
| `registered_model_name` | string | `house-price-regressor` |
| `mlflow_model_version` | string | versão do Registry |
| `mlflow_run_id` | string | origem do artefato |
| `training_run_id` | UUID | execução promotora |
| `candidate_family` | enum | família vencedora |
| `dataset_version` | string | linhagem |
| `dataset_checksum` | string | linhagem |
| `model_checksum` | string | SHA-256 do pacote |
| `metrics` | ModelMetrics | quatro métricas finais |
| `signature` | object | oito entradas e uma saída numérica |
| `dependency_lock_checksum` | string | SHA-256 do lockfile |
| `training_environment_version` | string | versão imutável da imagem de treino |
| `promoted_at` | datetime | UTC |
| `previous_model_version` | string/null | rollback |
| `status` | enum | `staging`, `current`, `superseded`, `invalid` |

Transição: `staging → current`; o campeão anterior passa de `current → superseded` na mesma seção
crítica. Um staging inválido vai para `invalid` e nunca altera `current.json`.

## ChampionPointer

Documento `current.json` substituído atomicamente no volume.

| Campo | Tipo | Regra |
|---|---|---|
| `schema_version` | string | contrato do manifesto |
| `model_version` | string | diretório existente em `models/` |
| `manifest_path` | string | caminho relativo, sem `..` |
| `manifest_sha256` | string | valida conteúdo antes do reload |
| `updated_at` | datetime | UTC |

## PredictionRequest e PredictionResult

`PredictionRequest` contém `instances` com 1 a 100 objetos. Cada objeto possui exatamente:
`MedInc`, `HouseAge`, `AveRooms`, `AveBedrms`, `Population`, `AveOccup`, `Latitude` e `Longitude`, todos
numéricos finitos. Campos extras são rejeitados.

`PredictionResult` contém `predictions` com o mesmo tamanho e ordem, `environment_version`,
`model_version`, `mlflow_run_id` e `request_id`. Cada previsão é numérica finita. O
`environment_version` identifica a imagem de inferência, não a versão do modelo.

## InferenceMetric

Agregado por janela temporal para consumo operacional pelo Grafana.

| Campo | Tipo | Regra |
|---|---|---|
| `window_started_at` | datetime | parte da chave, UTC |
| `window_seconds` | integer | positivo; padrão 60 |
| `environment_version` | string | parte da chave, não vazio |
| `model_version` | string | parte da chave, campeão atendente |
| `health_status` | enum | `ready`, `degraded`, `unavailable` |
| `request_count` | integer | ≥ 0 |
| `error_count` | integer | 0..`request_count` |
| `latency_p50_ms` | float/null | finito e ≥ 0 quando há requests |
| `latency_p95_ms` | float/null | finito e ≥ p50 |
| `latency_p99_ms` | float/null | finito e ≥ p95 |
| `latency_max_ms` | float/null | finito e ≥ p99 |
| `recorded_at` | datetime | UTC |

Unicidade: `(window_started_at, environment_version, model_version)`. O payload de entrada e os
atributos dos imóveis nunca são persistidos nesta entidade.

## WeeklyEvidence

Manifesto imutável produzido por toda execução semanal, com ou sem promoção.

| Campo | Tipo | Regra |
|---|---|---|
| `workflow_run_id` | string | chave única |
| `training_run_id` | UUID/null | nulo somente se falhar antes do treino |
| `previous_model_version` | string/null | campeão restaurado no início |
| `candidate_model_version` | string/null | candidato promovível |
| `effective_model_version` | string/null | campeão após todos os gates |
| `deployment_health` | enum | `passed`, `failed`, `not_run` |
| `rollback_result` | enum | `passed`, `failed`, `not_required`, `not_run` |
| `artifact_checksums` | object | mapa não vazio de SHA-256 |
| `completed_at` | datetime | UTC |

## ArtifactPlot

Metadado de gráficos armazenados no MLflow e, para o campeão, no volume.

| Campo | Tipo | Regra |
|---|---|---|
| `plot_id` | UUID | chave primária |
| `training_run_id` | UUID | execução de origem |
| `mlflow_run_id` | string | run associada |
| `candidate_family` | enum/null | nulo para gráfico global |
| `plot_type` | enum | `predicted_actual`, `residuals`, `error_distribution`, `feature_importance`, `optimization_history`, `parameter_importance` |
| `artifact_uri` | string | URI imutável |
| `created_at` | datetime | UTC |

## Relacionamentos

- Um `DatasetSnapshot` participa de muitas `TrainingRun`.
- Uma `TrainingRun` possui cinco `OptimizationStudy` e cinco `ModelCandidate` quando concluída.
- Um `OptimizationStudy` possui muitos `OptimizationTrial`.
- Uma `TrainingRun` promove zero ou um `ChampionModel`.
- Um `ChampionModel` referencia exatamente um `ModelCandidate` e pode apontar para o campeão anterior.
- Uma `TrainingRun` e seus candidatos possuem muitos `ArtifactPlot`.
- `ChampionPointer` referencia exatamente um `ChampionModel` em estado `current`.
- Um `ChampionModel` produz muitas janelas `InferenceMetric` enquanto atende solicitações.
- Cada execução agendada produz exatamente um `WeeklyEvidence`, mesmo quando falha sem candidato.
