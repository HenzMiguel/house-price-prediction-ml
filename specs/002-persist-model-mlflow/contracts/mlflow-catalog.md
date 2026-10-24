# MLflow Catalog Contract

## Recursos

| Recurso | Nome/valor |
|---|---|
| Experimento ativo | `MLFLOW_EXPERIMENT_NAME`, padrão `house-price-training-v2` |
| Experimento de recuperação | `house-price-model-reconciliation` |
| Registered Model | `house-price-regressor` |
| Alias | `champion` |
| Artifact URI novo | esquema `mlflow-artifacts:` |

Inicialização falha se o experimento ativo resolver para `file:` ou path absoluto. Experimentos
legados ficam somente leitura.

## Tags obrigatórias em run e ModelVersion

- `catalog.schema_version`;
- `catalog.model_version`;
- `catalog.manifest_sha256`;
- `catalog.model_sha256`;
- `catalog.training_run_id`;
- `catalog.dataset_sha256`;
- `catalog.origin=training|recovery`;
- `catalog.integrity=verified`;
- `catalog.publication_state=preparing|ready|approved|superseded|failed`.

Recuperações acrescentam `catalog.source_mlflow_run_id`,
`catalog.source_mlflow_model_version` e `catalog.reconciliation_id` quando conhecidos.

## Conteúdo visível

Cada modelo válido apresenta parâmetros, MAE/MSE/RMSE/R², referências de dados e código, família,
estado/decisão, modelo sob `model/`, manifesto e JSONs sob `metadata/`, plots sob `plots/` e versão
registrada. A versão é criada já com tags; mais de uma correspondência da mesma identidade é erro.

## Proxy

- Cliente recebe somente `MLFLOW_TRACKING_URI` HTTP(S).
- `/mlflow-artifacts` existe exclusivamente no container MLflow.
- Trainer, inferência e CLI não montam esse volume.
- Upload e download de validação atravessam o tracking server.
- Testes recusam URI `file:` ou absoluta em novas runs.

## Champion

Alias só aponta para a versão ativa do pacote indicado por `current.json`. Divergência produz
conflito. A resolução explícita pode reparar o alias para o pacote íntegro servido, nunca promover a
versão apontada apenas pelo MLflow.

## Integridade consultável

Uma versão é `ready` somente quando run/versão existem, tags coincidem com ledger, artifacts podem
ser baixados pelo proxy e checksums coincidem. Nenhum segredo conhecido pode aparecer em tags,
parâmetros, artifacts textuais ou diagnósticos.

