# House Price Prediction MLOps

Pipeline MLOps reproduzível para o dataset California Housing. O projeto compara regressão linear,
Ridge, Lasso, árvore de decisão e floresta aleatória, otimiza hiperparâmetros com Optuna, registra
experimentos no MLflow e promove o melhor modelo para um volume Docker imutável.

O serviço FastAPI utiliza o campeão do volume, enquanto PostgreSQL fornece uma projeção estável para
um Grafana externo. GitHub Actions executa CI e treinamento semanal. A implantação Azure for
Students está documentada como próximo incremento e não gera custos nesta feature.

## Arquitetura

- `trainer`: valida o snapshot offline, otimiza, avalia, registra e promove;
- `mlflow`: tracking server, registry e artefatos;
- `postgres`: persistência MLflow, Optuna e schema `observability`;
- `inference`: API HTTP não-root com reload atômico do campeão;
- Grafana: único serviço externo ao Compose, conectado ao PostgreSQL com usuário read-only.

Os volumes nomeados são `postgres-data`, `mlflow-artifacts` e `model-registry`. Não execute
`docker compose down -v` durante a operação normal.

Antes do primeiro `up`, crie os volumes externos estáveis com
`./scripts/manage_persistent_storage.sh create`. Inspecione-os com `inspect`; a destruição
coordenada exige backup e o token explícito `destroy --confirm destroy`.

A interface do MLflow fica disponível apenas no host local em <http://127.0.0.1:5000>.

## Requisitos

- Docker Engine e Compose v2;
- para desenvolvimento: Python 3.12–3.14 e `uv`;
- referência de SLO: Linux, 4 CPUs, 8 GiB RAM e 10 GiB livres.

## Execução local

```bash
cp .env.example .env
# Substitua todos os valores changeme em .env.
set -a
source .env
set +a
./scripts/manage_persistent_storage.sh create
docker compose config --quiet
docker compose build trainer inference mlflow
docker compose up -d --wait postgres mlflow
curl --fail http://127.0.0.1:5000/health
docker compose run --rm --entrypoint alembic \
  -e MIGRATION_DATABASE_URL="$MIGRATION_DATABASE_URL" \
  trainer upgrade head
docker compose up -d inference
docker compose run --rm trainer
```

O job one-shot `catalog-reconcile` aplica a migração do catálogo, verifica registry e artifact
proxy e reconcilia conteúdo antes de liberar o trainer. Consultas e manutenção usam:

```bash
docker compose run --rm --entrypoint model-catalog trainer list --json
docker compose run --rm --entrypoint model-catalog trainer verify --probe-artifacts --json
docker compose run --rm --entrypoint model-catalog trainer reconcile --mode check --json
```

Depois do primeiro campeão:

```bash
curl --fail http://localhost:8000/health/ready
curl --fail http://localhost:8000/v1/model
curl --fail --request POST http://localhost:8000/v1/predictions \
  --header 'Content-Type: application/json' \
  --data '{"instances":[{"MedInc":8.3252,"HouseAge":41,"AveRooms":6.9841,"AveBedrms":1.0238,"Population":322,"AveOccup":2.5556,"Latitude":37.88,"Longitude":-122.23}]}'
```

## Desenvolvimento e testes

```bash
uv sync --frozen --extra dev
uv run ruff check src scripts migrations tests
uv run pytest tests/unit tests/contract
uv run pytest tests/integration
./scripts/validate_quickstart.sh
```

O snapshot `data/california_housing.parquet` é versionado por manifesto e checksum. Para regenerá-lo
deliberadamente durante manutenção:

```bash
uv run python scripts/build_dataset_snapshot.py --output-dir data
```

Treinamentos normais não fazem download nem acessam a internet.

## MLflow e promoção

Cada execução cria uma run pai, cinco runs de família e trials aninhados. Os cinco finalistas usam o
mesmo holdout e registram MAE, MSE, RMSE e R². O vencedor precisa de R² ≥ 0,50 e, havendo campeão,
não pode aumentar MAE ou RMSE em mais de 5%. O desempate é RMSE, MAE, R² e ordem das famílias.

O pacote é validado em staging, movido para `models/<model_version>`, associado ao alias MLflow
`champion` e publicado por troca atômica de `current.json`. Falhas compensam o alias. Um resultado
idêntico ao campeão não é promovido novamente.

## Grafana externo

Use `grafana/datasource.example.yaml` com `grafana_reader` e importe
`grafana/dashboards/house-price-ml.json`. Os painéis exibem MAE/MSE/RMSE/R², candidatos, convergência
Optuna, estados, saúde, volume, erros e p50/p95/p99.

As regras em `grafana/alerts/house-price-alerts.yaml` cobrem execução semanal atrasada, ausência de
heartbeat da inferência e violações de qualidade. O padrão local publica PostgreSQL somente em
`127.0.0.1`; acesso remoto exige túnel ou TLS e firewall.

## Automação semanal

`.github/workflows/weekly-training.yml` usa agenda semanal e execução manual. Em runner hospedado,
restaura o último `weekly-state`, valida o snapshot, treina, cria backup e publica evidência por 90
dias. Configure os secrets:

- `MLOPS_POSTGRES_PASSWORD`;
- `MLOPS_MIGRATION_PASSWORD`;
- `MLOPS_PIPELINE_PASSWORD`;
- `MLOPS_GRAFANA_PASSWORD`.

## Operação e Azure

- [Operação, backup, restore e rollback](docs/operations.md)
- [Premissas para Azure for Students](docs/azure-deployment-assumptions.md)
- [Especificação e contratos](specs/001-train-container-metrics/)
- [Persistência e catálogo](specs/002-persist-model-mlflow/)
