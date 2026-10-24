# Implementation Plan: Treinamento Conteinerizado com Métricas

**Branch**: `001-train-container-metrics` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-train-container-metrics/spec.md`

## Summary

Construir uma pipeline local e reproduzível que valida o snapshot California Housing embutido na
imagem de treino, otimiza cinco famílias de regressão com Optuna, registra experimentos e artefatos
no MLflow e promove o melhor candidato conforme RMSE → MAE → R² → família. PostgreSQL persiste os
metadados de MLflow, estudos Optuna e uma projeção estável para o Grafana externo. O campeão é
materializado atomicamente em um volume Docker compartilhado, somente leitura para um serviço HTTP
de inferência. Gráficos de avaliação e otimização permanecem vinculados às runs e ao pacote campeão.

## Technical Context

**Language/Version**: Python 3.12; SQL PostgreSQL; YAML para Compose/CI; JSON para manifestos,
dashboard e contratos

**Primary Dependencies**: MLflow 3.x, Optuna 5.x, scikit-learn 1.9.x, FastAPI, Pydantic, pandas,
NumPy, SciPy, psycopg, SQLAlchemy/Alembic e servidor ASGI; versões exatas e hashes serão fixados no
lockfile

**Storage**: PostgreSQL com bancos separados para MLflow e Optuna e schema `observability` no banco
principal; volumes Docker
`postgres-data`, `mlflow-artifacts` e `model-registry`; snapshot Parquet e manifesto dentro da imagem
`trainer`

**Testing**: pytest, cobertura unitária, validação OpenAPI/JSON Schema/SQL, testes de integração com
Docker Compose e testes de resiliência da promoção atômica

**Target Platform**: Docker Engine com Compose v2 em host Linux; imagens OCI Linux não-root,
compatíveis com futura execução em Azure Container Instances

**Project Type**: Pipeline batch de ML + tracking server + serviço HTTP de inferência + fonte SQL de
observabilidade

**Performance Goals**: treino completo em até 30 minutos; stack utilizável em até 10 minutos;
95% de 100 previsões sequenciais em até 2 segundos; métricas consultáveis em até 5 minutos

**Constraints**: treino offline; seed 42 e trials seriais; holdout de 33%; cinco folds no treino;
R² mínimo 0,50; aumento relativo individual de MAE e RMSE limitado a 5% frente ao campeão, com
primeira promoção sujeita apenas ao gate absoluto; lote de predição entre 1 e 100; Grafana fora do
Compose; nenhuma implantação Azure nesta feature

**Scale/Scope**: 20.640 registros, oito features, cinco famílias de modelo, um trainer por vez, uma
instância local de inferência, retenção integral das runs e versões promovidas até remoção explícita

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

### Pre-research gate

| Princípio | Evidência planejada | Status |
|---|---|---|
| I. Experimentos rastreáveis | Runs MLflow pai/filha/trial registram código, dataset, parâmetros, métricas, assinatura e artefatos | PASS |
| II. Dados governados | Snapshot possui fonte, versão, SHA-256, schema e validação antes do treino; runtime não acessa API externa | PASS |
| III. Automação semanal | Workflow restaura o campeão, constrói, testa, treina, valida entrega/rollback e publica evidência durável | PASS |
| IV. Contêiner como entrega | Imagens são não-root; campeão usa volume imutável; premissas Azure e custo zero desta feature são documentados | PASS |
| V. Observabilidade | PostgreSQL expõe qualidade, saúde, latência, erros e volume; Grafana inclui alertas constitucionais | PASS |
| Portões de qualidade | Testes unitários, contratos, integração, build e critérios de promoção bloqueiam merge ou promoção | PASS |

### Post-design gate

O desenho de dados define linhagem e estados; os contratos fixam API, manifesto e views do Grafana;
o quickstart valida offline, persistência, falhas e rollback. Não há exceções constitucionais nem
dúvidas pendentes. Resultado: **PASS**.

## Architecture

### Componentes e fluxo

1. A imagem `trainer` contém o snapshot e seu manifesto. O job valida SHA-256, schema e qualidade.
2. O trainer obtém lock transacional, cria uma execução pai MLflow e prepara o split determinístico.
3. Para cada família, cria estudo Optuna persistente e runs aninhadas. A função objetivo usa somente
   validação cruzada no treino; cada melhor trial é avaliado uma vez no holdout.
4. O trainer registra métricas e gráficos no MLflow e faz UPSERT idempotente em `observability`.
5. Candidatos passam pelos gates e são ordenados por RMSE, MAE, R² e família. Sem elegível, o campeão
   atual não muda.
6. O vencedor é registrado no MLflow sem alterar o alias. Seu pacote completo é validado em staging,
   movido para diretório imutável e reaberto. Sob o lock de promoção, o alias `champion` é atualizado
   e então `current.json` é substituído atomicamente; falha na troca do ponteiro restaura o alias
   anterior. A inferência só aceita a nova versão quando ponteiro, manifesto e alias concordarem.
7. A inferência, com volume somente leitura, valida alterações de `current.json`, troca o modelo em
   memória sem descartar a versão anterior antes de a nova estar pronta e grava heartbeat por minuto.
8. O Grafana externo consulta somente views `observability` com usuário read-only. Imagens estáticas
   continuam como artefatos MLflow e no pacote do campeão.

### Serviços e persistência

| Serviço | Ciclo de vida | Dependências | Escrita persistente |
|---|---|---|---|
| `postgres` | contínuo | volume `postgres-data` | bancos/schemas MLflow, Optuna e observability |
| `mlflow` | contínuo | PostgreSQL saudável, `mlflow-artifacts` | metadados, Registry e artefatos |
| `trainer` | batch | PostgreSQL e MLflow saudáveis | MLflow, observability e `model-registry` RW |
| `inference` | contínuo | PostgreSQL e `model-registry` com campeão válido | agregados em `inference_metrics`; volume do modelo RO |
| Grafana externo | fora do Compose | PostgreSQL publicado de forma restrita | nenhuma; usuário somente leitura |

### Reprodutibilidade e otimização

- A divisão holdout e os folds usam seed 42; estimadores e `TPESampler` recebem a mesma seed.
- Optuna usa `n_jobs=1`, estudo nomeado por execução/família e espaços de busca versionados.
- Linear Regression executa um trial determinístico; Ridge, Lasso, Decision Tree e Random Forest
  recebem budgets configuráveis sob timeout global que preserva o limite de 30 minutos.
- Pré-processamento é encapsulado em pipelines por família para impedir ajuste sobre holdout.
- A tolerância numérica usada em testes de repetição é `1e-9` absoluto para métricas determinísticas.
- O pacote do campeão inclui dependências e assinatura; treino e inferência usam o mesmo lockfile.

### Gráficos e dashboards

- Por finalista: previsto × observado, resíduos e distribuição do erro.
- Quando suportado: coeficientes ou importância de features.
- Por estudo: histórico de otimização e importância de hiperparâmetros.
- Dashboard Grafana: MAE/MSE/RMSE/R² ao longo do tempo, comparação de candidatos e execuções,
  convergência de trials, duração/estado, promoção, saúde, volume, erros, p50/p95/p99 e idade da
  última métrica.
- Alertas versionados: nenhuma execução semanal bem-sucedida por oito dias, ausência de heartbeat da
  inferência por mais de cinco minutos (incluindo estado `No Data`) e violação dos gates de R², MAE
  ou RMSE.
- Todo gráfico registra `training_run_id`, `mlflow_run_id`, família, dataset e timestamp.

### Concorrência, falhas e rollback

- Um advisory lock PostgreSQL torna o treinamento/promoção single-flight; segunda execução encerra
  como `skipped_concurrent` sem alterar artefatos.
- Falha antes da troca de `current.json` mantém o campeão anterior; se o alias já tiver mudado, ele é
  restaurado antes de liberar o lock. Staging órfão só é limpo após confirmar que não está referenciado.
- Falha no UPSERT de observabilidade bloqueia promoção, mas a run MLflow termina como falha com etapa.
- Ausência de campeão mantém liveness 200 e readiness 503.
- Corrupção de manifesto/modelo impede reload e mantém a versão em memória; o evento é logado.
- `docker compose down -v` é operação destrutiva e não faz parte dos comandos normais do quickstart.

### Workflow semanal e evidência durável

- O workflow usa runner hospedado e restaura o último backup versionado de PostgreSQL/MLflow e o
  pacote campeão a partir dos artifacts da execução bem-sucedida mais recente; a ausência de backup
  caracteriza a primeira execução. A restauração e o checksum do snapshot embutido constituem a
  coleta governada deste incremento; aquisição por APIs externas pertence a uma feature futura.
- O workflow de treino publica a entrega sem depender da US2. A validação integrada posterior inicia
  a inferência com a versão efetiva, verifica readiness e previsão e testa rollback quando aplicável.
- Publica o pacote campeão, logs, métricas, gráficos e `weekly-evidence.json` como artefatos imutáveis
  retidos por no mínimo 90 dias; falhas preservam e republicam a identidade do campeão anterior.
- O manifesto semanal registra workflow/run IDs, versões anterior/candidata/efetiva, health, rollback,
  checksums e conclusão UTC, mesmo quando não houver promoção.
- A identidade de um resultado combina revisão do código, checksum do dataset, configuração do split,
  família, hiperparâmetros e checksum do modelo; resultado idêntico ao campeão termina como
  `succeeded_no_promotion` sem criar nova versão nem reaplicar o alias.

### Premissas para Azure for Students

- Esta feature não cria recursos Azure; seu gasto máximo na Azure é **US$ 0**.
- As imagens executam sem privilégios, recebem configuração por ambiente, expõem somente portas
  documentadas e não dependem de socket Docker, filesystem do host ou `localhost` entre contêineres.
- A futura implantação MUST fornecer persistência equivalente a `postgres-data`, `mlflow-artifacts`
  e `model-registry`, além de health checks e rollback equivalentes aos locais.
- CPU, memória, armazenamento, tráfego e tempo de execução de cada serviço serão medidos nesta
  feature e registrados como envelope para selecionar recursos dentro das cotas estudantis.
- Antes do deploy, a feature Azure MUST verificar crédito/cotas vigentes e aprovar estimativa e teto
  mensal; nenhuma escolha atual presume serviço pago ilimitado.

## Project Structure

### Documentation (this feature)

```text
specs/001-train-container-metrics/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── openapi.yaml
│   ├── champion-manifest.schema.json
│   ├── observability-schema.md
│   ├── training-cli.md
│   └── weekly-evidence.schema.json
└── tasks.md                 # criado posteriormente por $speckit-tasks
```

### Source Code (repository root)

```text
.
├── pyproject.toml
├── requirements.lock
├── compose.yaml
├── .env.example
├── data/
│   ├── california_housing.parquet
│   └── dataset-manifest.json
├── docker/
│   ├── trainer.Dockerfile
│   ├── inference.Dockerfile
│   ├── mlflow.Dockerfile
│   └── postgres/
│       └── init.sql
├── grafana/
│   ├── datasource.example.yaml
│   ├── alerts/house-price-alerts.yaml
│   └── dashboards/house-price-ml.json
├── docs/
│   ├── operations.md
│   └── azure-deployment-assumptions.md
├── migrations/
│   └── versions/
├── src/house_price/
│   ├── api/
│   │   ├── app.py
│   │   ├── model_service.py
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── data/
│   │   ├── manifest.py
│   │   └── validation.py
│   ├── training/
│   │   ├── cli.py
│   │   ├── dataset.py
│   │   ├── optimization.py
│   │   ├── pipeline.py
│   │   ├── publishing.py
│   │   ├── search_spaces.py
│   │   ├── evaluation.py
│   │   ├── plots.py
│   │   └── tracking.py
│   ├── tracking/
│   │   ├── mlflow_client.py
│   │   └── observability.py
│   ├── registry/
│   │   ├── manifest.py
│   │   ├── promotion.py
│   │   └── loader.py
│   └── settings.py
├── scripts/
│   └── build_dataset_snapshot.py
├── tests/
│   ├── contract/
│   ├── integration/
│   └── unit/
└── .github/workflows/
    ├── ci.yml
    └── weekly-training.yml
```

**Structure Decision**: Um único pacote Python separa domínios de dados, treino, tracking, registro e
API, compartilhando schemas e lockfile sem duplicar bibliotecas. Dockerfiles distintos preservam
privilégio mínimo e ciclos de vida. Contratos e migrações ficam versionados fora do código de runtime.

## Phase 0: Research Output

As decisões e alternativas estão consolidadas em [research.md](research.md). Todas as dúvidas de
runtime, tracking, otimização, persistência, Grafana, promoção, API e segurança foram resolvidas.

## Phase 1: Design Output

- [data-model.md](data-model.md): entidades, validações, relacionamentos e transições de estado.
- [contracts/openapi.yaml](contracts/openapi.yaml): contrato HTTP de saúde, modelo e predição.
- [contracts/champion-manifest.schema.json](contracts/champion-manifest.schema.json): pacote campeão.
- [contracts/observability-schema.md](contracts/observability-schema.md): tabelas e views do Grafana.
- [contracts/training-cli.md](contracts/training-cli.md): comando e códigos de saída do job batch.
- [contracts/weekly-evidence.schema.json](contracts/weekly-evidence.schema.json): evidência semanal.
- [quickstart.md](quickstart.md): cenários executáveis de validação ponta a ponta.

## Complexity Tracking

Nenhuma violação constitucional exige justificativa. A separação em quatro serviços decorre de
ciclos de vida, persistência e permissões distintos e permanece dentro de uma única solução local.
