# Operação local

## Perfil de referência

O perfil usado pelos SLOs possui Linux, 4 CPUs, 8 GiB de RAM, 10 GiB livres, Docker Engine e
Compose v2. O tempo de inicialização considera imagens e dependências previamente baixadas. Registre
CPU, memória, disco e duração produzidos por `tests/performance/test_end_to_end_slo.py` antes de
comparar ambientes diferentes.

O envelope do Compose limita `trainer` a 2 CPUs/3 GiB, PostgreSQL a 0,75 CPU/1,5 GiB, MLflow a
0,75 CPU/2,5 GiB e inferência a 0,5 CPU/1 GiB. Os três volumes compartilham o orçamento mínimo de 10 GiB do host;
monitore o uso antes de reter novas execuções.

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
docker run --rm -v house-price-mlops_model-registry:/source:ro -v "$PWD/backup:/backup" alpine:3.22 tar czf /backup/model-registry.tar.gz -C /source .
docker run --rm -v house-price-mlops_mlflow-artifacts:/source:ro -v "$PWD/backup:/backup" alpine:3.22 tar czf /backup/mlflow-artifacts.tar.gz -C /source .
sha256sum backup/* > backup/SHA256SUMS
```

## Restore

Valide `sha256sum -c backup/SHA256SUMS`, pare serviços que escrevem, restaure os dois volumes e use
`pg_restore --clean --if-exists` em `house_price`, `mlflow` e `optuna`. Execute `alembic upgrade head`, valide o manifesto/checksums do
campeão e só então inicie a inferência. O workflow semanal automatiza a mesma sequência em runner
hospedado usando o artifact `weekly-state` anterior.

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

`docker compose down` preserva volumes. `docker compose down -v` é destrutivo e só deve ser usado
após backup validado e autorização explícita.

