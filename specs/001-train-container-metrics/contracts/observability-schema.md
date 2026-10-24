# Observability SQL Contract

## Objetivo

O schema `observability` é a única interface SQL suportada para o Grafana externo. Tabelas internas
do MLflow e Optuna não fazem parte do contrato. Migrações preservam as views abaixo ou incrementam a
versão do datasource/dashboard em caso de quebra.

Todas as datas são `timestamptz` em UTC. Métricas são `double precision` finitas. O writer da
pipeline faz UPSERT por chaves naturais; reprocessar uma execução não cria duplicatas.

## Tabela `observability.training_runs`

| Coluna | Tipo | Restrições |
|---|---|---|
| `training_run_id` | uuid | primary key |
| `mlflow_parent_run_id` | text | unique, not null |
| `dataset_version` | text | not null |
| `dataset_checksum` | char(64) | not null |
| `code_revision` | text | not null |
| `started_at` | timestamptz | not null |
| `completed_at` | timestamptz | nullable enquanto ativa |
| `status` | text | enum lógico dos estados de `TrainingRun` |
| `failure_stage` | text | obrigatório quando `status = 'failed'` |
| `promoted_model_version` | text | nullable quando sem promoção |
| `updated_at` | timestamptz | not null |

## Tabela `observability.model_metrics`

| Coluna | Tipo | Restrições |
|---|---|---|
| `training_run_id` | uuid | FK lógica para `training_runs`, parte da PK |
| `candidate_family` | text | parte da PK; uma das cinco famílias |
| `mlflow_run_id` | text | unique, not null |
| `best_trial_number` | integer | not null, ≥ 0 |
| `mae` | double precision | not null, finito, ≥ 0 |
| `mse` | double precision | not null, finito, ≥ 0 |
| `rmse` | double precision | not null, finito, ≥ 0 |
| `r2` | double precision | not null, finito |
| `eligible` | boolean | not null |
| `promoted` | boolean | not null; no máximo um `true` por run |
| `ineligibility_reasons` | jsonb | array, vazio quando elegível |
| `measured_at` | timestamptz | not null |
| `artifact_uri` | text | not null |

Chave primária: `(training_run_id, candidate_family)`. Índices: `measured_at`,
`candidate_family`, `(promoted, measured_at desc)`.

## Tabela `observability.optimization_trials`

| Coluna | Tipo | Restrições |
|---|---|---|
| `study_name` | text | parte da PK |
| `trial_number` | integer | parte da PK, ≥ 0 |
| `training_run_id` | uuid | not null |
| `candidate_family` | text | not null |
| `mlflow_run_id` | text | unique, not null |
| `objective_rmse` | double precision | finito quando concluído |
| `state` | text | `running`, `complete`, `pruned` ou `failed` |
| `duration_seconds` | double precision | nullable, ≥ 0 |
| `parameters_json` | jsonb | not null |
| `completed_at` | timestamptz | nullable |

Chave primária: `(study_name, trial_number)`. Índices: `(training_run_id, candidate_family)` e
`completed_at`.

## Tabela `observability.artifact_plots`

| Coluna | Tipo | Restrições |
|---|---|---|
| `plot_id` | uuid | primary key |
| `training_run_id` | uuid | not null |
| `mlflow_run_id` | text | not null |
| `candidate_family` | text | nullable para gráfico global |
| `plot_type` | text | tipo enumerado em `data-model.md` |
| `artifact_uri` | text | not null |
| `created_at` | timestamptz | not null |

## Tabela `observability.inference_metrics`

| Coluna | Tipo | Restrições |
|---|---|---|
| `window_started_at` | timestamptz | parte da PK, UTC |
| `window_seconds` | integer | > 0; padrão 60 |
| `environment_version` | text | parte da PK, not null |
| `model_version` | text | parte da PK, not null |
| `health_status` | text | `ready`, `degraded` ou `unavailable` |
| `request_count` | bigint | ≥ 0 |
| `error_count` | bigint | entre 0 e `request_count` |
| `latency_p50_ms` | double precision | nullable, finito e ≥ 0 |
| `latency_p95_ms` | double precision | nullable, ≥ p50 |
| `latency_p99_ms` | double precision | nullable, ≥ p95 |
| `latency_max_ms` | double precision | nullable, ≥ p99 |
| `recorded_at` | timestamptz | not null, UTC |

Chave primária: `(window_started_at, environment_version, model_version)`. Nenhum payload ou feature
de imóvel pode ser armazenado nesta tabela.

## Views públicas para Grafana

### `observability.grafana_model_metric_history`

Uma linha por candidato e execução, com:

`measured_at`, `training_run_id`, `candidate_family`, `mae`, `mse`, `rmse`, `r2`, `eligible`,
`promoted`, `dataset_version`, `model_version`.

Uso: séries temporais de MAE/RMSE/R², filtro por família e anotação de promoção.

### `observability.grafana_candidate_comparison`

Uma linha por candidato da execução selecionada, com:

`training_run_id`, `candidate_family`, `mae`, `mse`, `rmse`, `r2`, `eligible`, `promoted`,
`ineligibility_reasons`, `artifact_uri`.

Uso: barras/tabela que comparam os cinco finalistas.

### `observability.grafana_training_status`

Uma linha por execução, com:

`started_at`, `completed_at`, `duration_seconds`, `training_run_id`, `status`, `failure_stage`,
`dataset_version`, `promoted_model_version`, `metric_age_seconds`.

Uso: duração, sucesso/falha, promoção e indicador de métricas desatualizadas. Uma métrica é
considerada desatualizada quando a última execução concluída tem mais de oito dias.

### `observability.grafana_optuna_convergence`

Uma linha por trial concluído, com:

`completed_at`, `training_run_id`, `candidate_family`, `study_name`, `trial_number`,
`objective_rmse`, `best_so_far_rmse`, `duration_seconds`, `state`.

Uso: convergência e custo de otimização.

### `observability.grafana_inference_operations`

Uma linha por janela e versão, com:

`window_started_at`, `environment_version`, `model_version`, `health_status`, `request_count`,
`error_count`, `error_rate`, `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms`, `latency_max_ms`.

Uso: saúde, volume, erros, distribuição de latência e alerta de indisponibilidade.

## Permissões

- `pipeline_writer`: `USAGE` no schema e `SELECT/INSERT/UPDATE` nas cinco tabelas; sem DDL.
- `grafana_reader`: `USAGE` no schema e `SELECT` somente nas cinco views; sem acesso às tabelas,
  schemas do MLflow/Optuna ou funções mutáveis.
- Migrações: conta separada usada somente por job explícito de inicialização.
- PostgreSQL é publicado em `127.0.0.1` por padrão. Acesso remoto exige TLS, firewall ou túnel e fica
  fora do escopo local.

## Contrato do dashboard

O arquivo versionado `grafana/dashboards/house-price-ml.json` deve oferecer variáveis de período,
execução e família, e os painéis:

1. estado e duração da última execução;
2. campeão atual e versão do dataset;
3. MAE, MSE, RMSE e R² ao longo do tempo;
4. comparação dos cinco candidatos;
5. convergência Optuna por família;
6. promoções, rejeições e falhas;
7. saúde, volume, erros e p50/p95/p99 da inferência;
8. idade da última métrica, alertando após oito dias.

As regras em `grafana/alerts/house-price-alerts.yaml` devem alertar para: nenhuma execução semanal
bem-sucedida por mais de oito dias, inferência indisponível e violação dos gates de R²/MAE/RMSE.
Todo estado de alerta deve ficar consultável em até cinco minutos.

Consultas devem usar macros de tempo do Grafana e nunca concatenar entrada livre em identificadores.
