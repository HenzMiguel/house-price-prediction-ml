# Data Model: Persistência e Catálogo de Modelos

## Visão geral

O pacote no volume é autoridade sobre os bytes e a identidade estável; MLflow é a interface oficial
de consulta; o schema PostgreSQL `catalog` coordena vínculos e operações. IDs são imutáveis,
timestamps usam UTC, checksums usam SHA-256 minúsculo e paths persistidos são relativos.

## PersistedModelPackage

Diretório imutável `models/<model_version>/`.

| Campo | Tipo | Regra |
|---|---|---|
| `schema_version` | enum | `1.0.0` legado ou `2.0.0` atual |
| `model_version` | string | identidade determinística, igual ao diretório |
| `training_run_id` | UUID | execução de negócio original |
| `source_mlflow_run_id` | string | run original |
| `source_mlflow_model_version` | string/null | versão original, apenas histórica |
| `candidate_family` | enum | uma das cinco famílias existentes |
| `code_revision` | string | obrigatório em v2 |
| `dataset` | object | nome, versão, checksum, schema e linhas |
| `parameters` | object | parâmetros efetivos, obrigatório em v2 |
| `metrics` | object | MAE/MSE/RMSE não negativos e R², todos finitos |
| `signature` | object | oito entradas canônicas e saída numérica |
| `artifacts` | object | paths relativos e checksums de todos os arquivos |
| `promoted_at` | datetime | UTC |

V2 contém diretório de modelo MLflow completo, `parameters.json`, `metrics.json`, plots e lockfile.
Nenhum symlink, path absoluto ou `..` é aceito. Validação ocorre antes de desserialização.

## catalog.model_entries

Vínculo atual entre pacote e MLflow.

| Campo | Tipo | Regra |
|---|---|---|
| `model_version` | string | PK; identidade local estável |
| `manifest_schema_version` | string | `1.0.0` ou `2.0.0` |
| `manifest_sha256` | char(64) | obrigatório |
| `model_sha256` | char(64) | obrigatório |
| `package_relpath` | string | único; sob `models/` |
| `training_run_id` | UUID | obrigatório |
| `source_mlflow_run_id` | string/null | proveniência original |
| `source_mlflow_model_version` | string/null | proveniência original |
| `active_mlflow_run_id` | string/null | vínculo atual acessível |
| `active_mlflow_model_version` | string/null | único quando preenchido |
| `registered_model_name` | string | `house-price-regressor` |
| `integrity_status` | enum | estados abaixo |
| `catalog_status` | enum | estados abaixo |
| `lifecycle_status` | enum | estados abaixo |
| `promotion_status` | enum | estados abaixo |
| `diagnostic_code` | string/null | código estável e sanitizado |
| `first_seen_at` | datetime | UTC |
| `verified_at` | datetime/null | última verificação completa |
| `last_reconciled_at` | datetime/null | UTC |
| `revision` | integer | ≥ 1, controle otimista |

Constraints: `model_version`, `package_relpath` e versão MLflow ativa são únicos; versão ativa só é
preenchida com catálogo registrado; pacote promovível exige integridade verificada e lifecycle ativo.

### Estados ortogonais

- `integrity_status`: `unknown → verifying → verified | invalid | missing | unsupported`.
- `catalog_status`: `unregistered → registering → registered | registration_failed | conflict`.
- `lifecycle_status`: `active → quarantined | deletion_requested → trashed → deleted`.
- `promotion_status`: `candidate | champion | superseded | rejected`.

Somente `verified + registered + active` pode tornar-se `champion`. Falha do MLflow não altera a
integridade local. Uma identidade tombstonada nunca volta automaticamente para `active`.

## catalog.reconciliation_runs

| Campo | Tipo | Regra |
|---|---|---|
| `reconciliation_id` | UUID | PK |
| `trigger` | enum | `manual`, `startup`, `weekly`, `restore` |
| `mode` | enum | `check`, `apply` |
| `scan_fingerprint` | char(64) | hash determinístico dos itens observados |
| `status` | enum | `running`, `succeeded`, `partial`, `failed`, `lock_unavailable` |
| `started_at` | datetime | UTC |
| `completed_at` | datetime/null | posterior ao início |
| `scanned_count` | integer | ≥ 0 |
| `registered_count` | integer | 0..scanned |
| `recovered_count` | integer | 0..scanned |
| `quarantined_count` | integer | 0..scanned |
| `unchanged_count` | integer | 0..scanned |
| `mlflow_evidence_run_id` | string/null | run de evidência quando disponível |

Transições: `running → succeeded|partial|failed`; ausência de lock produz `lock_unavailable` sem
mutação. Modo `check` não cria run/model version, alias, tombstone ou arquivo.

## catalog.reconciliation_items

| Campo | Tipo | Regra |
|---|---|---|
| `reconciliation_id` | UUID | FK e parte da PK |
| `package_relpath` | string | parte da PK; path relativo |
| `model_version` | string/null | identidade observada |
| `manifest_sha256` | char(64)/null | quando manifesto legível |
| `action` | enum | `verified`, `registered`, `recovered`, `quarantined`, `unchanged`, `conflict` |
| `result` | enum | `succeeded`, `failed`, `skipped` |
| `reason_code` | string/null | diagnóstico sanitizado |
| `mlflow_run_id` | string/null | vínculo resultante |
| `mlflow_model_version` | string/null | vínculo resultante |
| `occurred_at` | datetime | UTC |

PK: `(reconciliation_id, package_relpath)`. Um relatório possui exatamente a mesma contagem de
itens que `scanned_count`.

## catalog.operation_events

Ledger append-only para promoção, reconciliação, resolução e remoção.

| Campo | Tipo | Regra |
|---|---|---|
| `event_id` | UUID | PK |
| `operation_id` | UUID | correlação da saga/comando |
| `operation` | enum | `publish`, `reconcile`, `resolve_champion`, `delete`, `purge` |
| `model_version` | string/null | alvo |
| `from_state` | object/null | snapshot mínimo anterior |
| `to_state` | object/null | snapshot mínimo posterior |
| `phase` | string | fase estável e retomável |
| `result` | enum | `started`, `succeeded`, `failed`, `compensated` |
| `reason_code` | string/null | sem segredo |
| `occurred_at` | datetime | UTC |

Eventos não são atualizados ou removidos. Estado atual deriva de `model_entries`; eventos explicam
como ele foi alcançado.

## catalog.deletion_requests

| Campo | Tipo | Regra |
|---|---|---|
| `deletion_id` | UUID | PK |
| `model_version` | string | único enquanto ativo |
| `requested_at` | datetime | UTC |
| `confirmed_at` | datetime/null | somente após token exato |
| `state` | enum | `planned`, `confirmed`, `trashed`, `purged`, `refused`, `failed` |
| `package_relpath` | string | origem |
| `trash_relpath` | string/null | `.trash/<deletion_id>/<model_version>` |
| `impact` | object | vínculos, aliases e referências compartilhadas |
| `reason_code` | string/null | obrigatório em recusa/falha |

Campeão pelo ponteiro ou alias, último modelo íntegro e item de mutação ativa são sempre recusados.
`trashed` é recuperável; `purged` é irreversível dentro desta feature.

## MLflowCatalogRecord

Projeção lógica consultada pela interface MLflow.

| Campo | Local | Regra |
|---|---|---|
| parâmetros/métricas | run | completos e iguais ao pacote |
| dataset/código | tags | referências imutáveis |
| identidade/checksums | tags | iguais a `model_entries` |
| origem | tags | `training` ou `recovery` |
| modelo | artifact `model/` | download via proxy e formato MLflow |
| manifesto/metadados | artifacts `metadata/` | verificáveis |
| versão | Model Registry | uma ativa por identidade local |
| alias `champion` | Model Registry | zero ou uma versão |

## ChampionPointer

Contrato existente de `current.json`, acrescido de validação cruzada com ledger e alias. O arquivo é
gravado com temporário exclusivo, flush, fsync, `os.replace` e fsync do diretório pai. Não contém
credenciais nem URI de backend.

## Invariantes globais

1. No máximo uma entrada possui `promotion_status=champion`.
2. Um champion concorda com pacote válido, `current.json`, ledger e alias MLflow.
3. Uma identidade local liga-se a no máximo uma versão MLflow ativa e vice-versa.
4. Pacotes publicados nunca são sobrescritos; conteúdo diferente recebe nova identidade.
5. Reconciliação não desserializa o modelo e não promove item descoberto.
6. Repetir `reconcile --apply` sobre o mesmo estado não cria run, versão ou evento semântico novo.
7. Restore inconsistente nunca apaga automaticamente o lado mais novo.
8. Nenhum segredo aparece em manifestos, tags, parâmetros, relatórios ou eventos.
9. V1 sem run/artifact original permanece preservado, mas não vira registered/champion.
10. Tombstone impede ressurreição automática após restore de backup antigo.

## Relacionamentos

- Um pacote possui zero ou uma `model_entry` atual e muitos eventos.
- Uma entrada referencia zero ou um registro MLflow ativo e preserva IDs de origem.
- Uma reconciliation run possui muitos items.
- Uma deletion request pertence a uma entrada e gera eventos append-only.
- `current.json` referencia exatamente um pacote e, quando saudável, uma entrada champion.

