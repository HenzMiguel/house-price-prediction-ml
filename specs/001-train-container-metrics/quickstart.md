# Quickstart: Validação Ponta a Ponta

Este guia descreve como validar a feature depois da implementação. Ele não substitui os contratos em
`contracts/` nem contém código da aplicação.

## Pré-requisitos

- Docker Engine e Docker Compose v2;
- pelo menos 4 CPUs, 8 GiB de RAM e 10 GiB livres para o teste de referência;
- `curl` e um cliente PostgreSQL opcionais para inspeção;
- Grafana externo somente para o cenário de dashboard.

Não use `docker compose down -v`: a opção `-v` remove deliberadamente os volumes com experimentos,
métricas e modelos.

## 1. Preparar configuração

```bash
cp .env.example .env
set -a
source .env
set +a
docker compose config --quiet
```

Defina credenciais locais fortes para as contas de migração, pipeline e Grafana. Confirme que o
PostgreSQL está publicado somente em `127.0.0.1` e que nenhuma credencial aparece no Compose
renderizado ou nas imagens.

Resultado esperado: configuração válida, três volumes nomeados e quatro serviços (`postgres`,
`mlflow`, `trainer`, `inference`).

## 2. Construir e verificar imagens

```bash
docker compose build --pull trainer inference mlflow
docker compose run --rm trainer python -m house_price.data.manifest verify
```

Resultado esperado: o snapshot possui 20.640 linhas, oito features, target, versão e checksum
válidos. O verificador não acessa a internet. As imagens `trainer` e `inference` executam com UID
diferente de zero.

## 3. Subir persistência, tracking e aplicar migrações

```bash
docker compose up -d --wait postgres mlflow
docker compose run --rm --entrypoint alembic \
  -e MIGRATION_DATABASE_URL="$MIGRATION_DATABASE_URL" trainer upgrade head
docker compose up -d inference
docker compose ps
curl --fail http://localhost:8000/health/live
curl --fail-with-body http://localhost:8000/health/ready
```

Resultado esperado antes do primeiro treino: PostgreSQL e MLflow ficam saudáveis; liveness responde
200; readiness responde 503 porque ainda não existe campeão.

## 4. Executar treinamento

```bash
docker compose run --rm trainer train
```

Resultado esperado em até 30 minutos:

- uma run pai, cinco runs de família e trials aninhados no MLflow;
- regressão linear, Ridge, Lasso, árvore e floresta avaliadas no mesmo holdout;
- MAE, MSE, RMSE e R² para cada finalista;
- gráficos de previsto × observado, resíduos, erros e otimização;
- projeções SQL para o Grafana;
- candidato selecionado por RMSE, MAE, R² e família;
- se os gates forem satisfeitos, diretório imutável validado, alias `champion` e `current.json`
  coordenados com compensação em caso de falha.

Valide novamente:

```bash
curl --fail http://localhost:8000/health/ready
curl --fail http://localhost:8000/v1/model
```

Resultado esperado: o serviço recarrega o campeão, readiness responde 200 e informa
`environment_version` e `model_version`; os metadados coincidem com a imagem, o MLflow e o manifesto.

## 5. Validar previsão

```bash
curl --fail --request POST http://localhost:8000/v1/predictions \
  --header 'Content-Type: application/json' \
  --data '{
    "instances": [{
      "MedInc": 8.3252,
      "HouseAge": 41,
      "AveRooms": 6.9841,
      "AveBedrms": 1.0238,
      "Population": 322,
      "AveOccup": 2.5556,
      "Latitude": 37.88,
      "Longitude": -122.23
    }]
  }'
```

Resultado esperado: status 200, uma previsão numérica, `environment_version`, `model_version`,
`mlflow_run_id` e `request_id`. Remover um campo, adicionar um desconhecido, enviar infinito ou mais
de 100 instâncias deve retornar 422 conforme [openapi.yaml](contracts/openapi.yaml).

## 6. Configurar Grafana externo

1. Adicione uma fonte PostgreSQL apontando para o host e porta definidos em `.env`.
2. Use exclusivamente `grafana_reader` e o schema `observability`.
3. Teste a conexão e importe `grafana/dashboards/house-price-ml.json`.
4. Selecione a última execução e compare as cinco famílias.

Resultado esperado: painéis exibem histórico de MAE/MSE/RMSE/R², candidato promovido, convergência
Optuna, duração, saúde, volume, erros, p50/p95/p99 e idade da última métrica. Regras alertam para
falha semanal, indisponibilidade e violação de qualidade em até cinco minutos. O usuário não consegue
escrever nem consultar schemas internos. Consulte [observability-schema.md](contracts/observability-schema.md).

## 7. Validar persistência

```bash
docker compose down
docker compose up -d postgres mlflow inference
curl --fail http://localhost:8000/health/ready
curl --fail http://localhost:8000/v1/model
```

Resultado esperado: runs, métricas, artefatos e campeão sobrevivem; o mesmo `model_version` volta a
atender previsões.

## 8. Executar testes e contratos

```bash
docker compose run --rm trainer pytest tests/unit tests/contract
docker compose run --rm trainer pytest tests/integration
```

Resultado esperado: contratos OpenAPI, manifesto e SQL válidos; ranking determinístico; promoção
atômica; volume read-only na inferência; persistência e treinamento offline comprovados.

## 9. Cenários de resiliência

Execute os testes automatizados que:

1. interrompem o trainer antes/depois da troca do alias e de `current.json`, verificando compensação;
2. corrompem um staging sem tocar no campeão;
3. apresentam um candidato abaixo do gate;
4. iniciam dois trainers simultaneamente;
5. tornam a projeção de observabilidade indisponível;
6. apresentam manifesto/checksum inválido ao watcher da inferência.

Resultado esperado: o campeão anterior continua servindo; somente um trainer obtém lock; a falha
fica correlacionada no MLflow, logs e PostgreSQL; nenhuma promoção parcial ocorre.

## 10. Encerrar sem perder dados

```bash
docker compose down
```

Os volumes permanecem. A remoção deles é uma ação destrutiva separada e exige backup ou intenção
explícita.
