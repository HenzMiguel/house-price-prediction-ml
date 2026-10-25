# Operação local

## Perfil de referência

O perfil usado pelos SLOs possui Linux, 4 CPUs, 8 GiB de RAM, 10 GiB livres, Docker Engine e
Compose v2. O tempo de inicialização considera imagens e dependências previamente baixadas. Registre
CPU, memória, disco e duração produzidos por `tests/performance/test_end_to_end_slo.py` antes de
comparar ambientes diferentes.

O envelope do Compose limita `trainer` a 2 CPUs/3 GiB, PostgreSQL a 0,75 CPU/1,5 GiB, MLflow a
0,75 CPU/2,5 GiB e inferência a 0,5 CPU/1 GiB. Os três volumes compartilham o orçamento mínimo de 10 GiB do host;
monitore o uso antes de reter novas execuções.

## Ciclo de vida dos volumes

Os volumes externos possuem nomes estáveis: `house-price-postgres-data`,
`house-price-mlflow-artifacts` e `house-price-model-registry`. Crie e verifique sem alterar dados:

```bash
./scripts/manage_persistent_storage.sh create
./scripts/manage_persistent_storage.sh inspect
```

Somente após backup validado e parada da stack, remova-os com
`./scripts/manage_persistent_storage.sh destroy --confirm destroy`. O script recusa volumes sem o
rótulo gerenciado. Reserve ao menos 10 GiB somados e alerte antes de 80% de uso.

## Componentes e portas

- PostgreSQL: publicado somente em `127.0.0.1:${POSTGRES_HOST_PORT}` para Grafana no mesmo host;
- inferência: `127.0.0.1:${INFERENCE_HOST_PORT}`;
- MLflow: publicado somente em `127.0.0.1:${MLFLOW_HOST_PORT}` para inspeção local;
- trainer e rede de treinamento: sem publicação externa;
- Grafana: serviço externo, no mesmo host. Acesso remoto ao PostgreSQL exige túnel ou TLS e firewall.

As quatro senhas são fornecidas por `.env` local ou GitHub Secrets. Nunca registre `.env`, dumps,
payloads de imóveis ou credenciais em logs e artifacts.

## Backup

Faça backup consistente antes de manutenção:

```bash
mkdir -p backup
for database in house_price mlflow optuna; do
  docker compose exec -T postgres pg_dump --format=custom --username "$POSTGRES_USER" "$database" > "backup/${database}.dump"
done
docker run --rm -v house-price-model-registry:/source:ro -v "$PWD/backup:/backup" alpine:3.22 tar czf /backup/model-registry.tar.gz -C /source .
docker run --rm -v house-price-mlflow-artifacts:/source:ro -v "$PWD/backup:/backup" alpine:3.22 tar czf /backup/mlflow-artifacts.tar.gz -C /source .
sha256sum backup/* > backup/SHA256SUMS
```

## Restore

Valide `sha256sum -c backup/SHA256SUMS` e restaure nesta ordem: pare escritores; restaure os três
bancos; restaure `mlflow-artifacts`; restaure `model-registry`; execute `mlflow-migrate`; inicie
MLflow; execute `catalog-reconcile`; e rode `model-catalog verify --probe-artifacts --json`. Só
então libere novo treinamento. A inferência pode continuar servindo um campeão local íntegro durante
indisponibilidade do catálogo. O workflow semanal automatiza essa sequência.

Antes de qualquer migração, retenha dumps e checksums. Para rollback, pare escritores, restaure o
dump e volumes do mesmo conjunto, execute a versão anterior das imagens e verifique o campeão. Não
faça downgrade destrutivo do catálogo sobre dados que não estejam em backup.

## Verificação, reconciliação e resolução

`model-catalog verify` é read-only. `reconcile --mode check` apenas relata; `--mode apply` usa lock,
adota versões íntegras e nunca promove. Depois de restore, divergência de alias permanece explícita.
Repare apenas em direção ao pacote já servido e validado:

```bash
model-catalog resolve-champion --prefer volume --apply --confirm VERSION --json
```

Falha parcial mantém o campeão anterior. Código 8 indica lock ocupado e deve ser repetido com
backoff; códigos 4/6 indicam dependência/persistência e exigem correção antes de nova mutação.

## Remoção protegida

`model-catalog delete --model-version VERSION --json` mostra impacto sem mutar. A aplicação exige
`--apply --confirm VERSION`, recusa ponteiro/alias champion, último modelo íntegro e mutação ativa,
cria tombstone e move o pacote para `.trash`. A remoção física é separada e irreversível:

```bash
model-catalog purge --deletion-id UUID --apply --confirm UUID --json
```

Não copie manualmente um pacote tombstonado de backup: a reconciliação o mantém em conflito. Para
falha após trash, repita `delete` com a mesma versão; a operação converge sem mover novamente.

## Rollback

Cada manifesto contém `previous_model_version`. Para rollback, valide o pacote anterior, atualize o
alias MLflow `champion` e substitua `current.json` atomicamente pelo ponteiro anterior. Confirme
`/health/ready`, `/v1/model` e uma previsão. Se qualquer validação falhar, restaure alias e ponteiro
originais antes de liberar o lock de promoção.

## Alertas e diagnóstico

O Grafana avalia a cada minuto:

- última execução semanal com mais de oito dias;
- ausência de heartbeat `ready` por cinco minutos, incluindo `No Data`;
- candidatos que violaram os gates de R², MAE ou RMSE.

Correlacione incidentes por `training_run_id`, `mlflow_run_id`, `model_version`,
`environment_version` e `request_id`. A inferência nunca registra atributos enviados pelo usuário.

## Remoção de dados

`docker compose down` preserva volumes externos. Mesmo `down -v` não é o procedimento de remoção;
use apenas o script gerenciado acima após backup validado e autorização explícita.

