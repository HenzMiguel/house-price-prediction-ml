# Quickstart: Persistência e Catálogo de Modelos

Guia de validação após implementação. Consulte [catalog-cli.md](contracts/catalog-cli.md) e
[mlflow-catalog.md](contracts/mlflow-catalog.md) para os contratos completos.

## Pré-requisitos

- Docker Engine e Compose v2;
- `.env` com credenciais locais não triviais;
- 4 CPUs, 8 GiB de RAM e 10 GiB livres;
- `curl`; Python/uv somente para os portões locais.

## 1. Criar volumes persistentes e validar configuração

```bash
./scripts/manage_persistent_storage.sh create
set -a
source .env
set +a
docker compose config --quiet
docker compose build trainer inference mlflow
```

Esperado: três volumes externos com nomes estáveis; somente MLflow monta `mlflow-artifacts`; trainer
monta `model-registry` RW e inferência RO; imagens executam sem root; portas ficam em `127.0.0.1`.

## 2. Migrar e iniciar o tracking

```bash
docker compose up -d --wait postgres
docker compose run --rm mlflow-migrate
docker compose up -d --wait mlflow
curl --fail http://127.0.0.1:5000/health
docker compose run --rm --entrypoint model-catalog trainer verify --probe-artifacts --json
```

Esperado: schemas MLflow e `catalog` atuais; client/server na mesma versão; sonda de upload/download
via proxy concluída e removida. O experimento ativo usa URI `mlflow-artifacts:`, nunca `file:`.

## 3. Publicar e consultar um modelo

```bash
docker compose run --rm trainer
docker compose run --rm --entrypoint model-catalog trainer list --json
docker compose run --rm --entrypoint model-catalog trainer verify --json
```

Em até dois minutos, espere pacote v2 íntegro, entrada ledger `verified/registered/active/champion`,
run com parâmetros/métricas/linhagem/artifacts, versão `house-price-regressor`, alias `champion` e
concordância com `current.json`. Confirme em <http://127.0.0.1:5000> que o campeão e sua origem podem
ser identificados em até dois minutos.

## 4. Comprovar persistência em cinco ciclos

Registre IDs e checksums retornados e repita cinco vezes:

```bash
docker compose down
docker compose up -d --wait postgres mlflow inference
docker compose run --rm --entrypoint model-catalog trainer verify --json
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:8000/v1/model
```

Esperado: mesmos modelos, runs, versões, alias, parâmetros, métricas e checksums; nenhuma nova
entidade; inferência pronta sem retreinamento. Valide também um ciclo com `up --force-recreate`.

## 5. Reconciliar conteúdo existente

Em volumes isolados de teste, prepare ao menos dez pacotes entre v2 íntegros, v1 com run existente e
itens inválidos. Execute:

```bash
docker compose run --rm --entrypoint model-catalog trainer reconcile \
  --mode check --trigger manual --json
docker compose run --rm --entrypoint model-catalog trainer reconcile \
  --mode apply --trigger manual --json
```

Repita `apply` cinco vezes. Esperado: cada íntegro aparece uma vez; v1 vinculável preserva a origem;
item inválido ou v1 sem artifact original fica quarantined; repetições ficam unchanged, sem novas
runs/versões. Nenhum pacote descoberto troca o campeão.

## 6. Validar restore e conflitos

Teste separadamente:

1. volume de modelos mais novo que banco/MLflow;
2. banco/MLflow mais novo que o volume;
3. artifact store ausente;
4. alias divergente do ponteiro;
5. ponteiro ausente ou corrompido;
6. tombstone mais novo com backup antigo do pacote.

Para pacote v2 autossuficiente ausente no MLflow:

```bash
docker compose run --rm --entrypoint model-catalog trainer reconcile \
  --mode apply --trigger restore --json
```

Esperado: recuperação auditável preserva IDs de origem e cria um único vínculo ativo. Conflito de
champion não é resolvido implicitamente. Para reparar o alias ao modelo local validado:

```bash
docker compose run --rm --entrypoint model-catalog trainer resolve-champion \
  --prefer volume --apply --confirm VERSION --json
```

## 7. Validar falhas atômicas e concorrência

Os testes de integração devem interromper após upload, criação de ModelVersion, materialização do
pacote, alteração do alias e troca do ponteiro; também devem executar promoção/reconciliação/delete
concorrentes. Esperado: uma repetição converge; não há duplicata; último campeão íntegro continua
servindo; estado parcial nunca aparece approved/champion.

## 8. Validar exclusão protegida

```bash
docker compose run --rm --entrypoint model-catalog trainer delete \
  --model-version VERSION --json
docker compose run --rm --entrypoint model-catalog trainer delete \
  --model-version VERSION --apply --confirm VERSION --json
```

O primeiro comando só mostra impacto. O segundo cria tombstone e trash para versão superseded.
Champion, alias champion, último modelo íntegro e operação concorrente são recusados. Purga exige
novo comando e confirmação pelo deletion ID.

## 9. Executar portões

```bash
uv run ruff check src tests scripts migrations
uv run pytest tests/unit tests/contract
uv run pytest tests/integration -m "not docker"
RUN_DOCKER_PERSISTENCE_TEST=1 uv run pytest \
  tests/integration/test_volume_persistence.py -m docker
```

Esperado: schemas, CLI, migração, tags, proxy, integridade, idempotência, crash recovery, permissões,
segredos e cinco ciclos aprovados.

## 10. Validar workflow semanal

Dispare o workflow manual em branch de teste. Ele deve restaurar banco/volumes, migrar, reconciliar
antes do treino, bloquear promoção se o campeão não for recuperável e incluir relatório/checksums na
evidência semanal, mesmo sem novo modelo aprovado.

