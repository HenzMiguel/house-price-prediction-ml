# Resultados de validação

**Data**: 2026-10-24  
**Revisão base**: `fcf107d` com alterações desta feature no worktree  
**Status**: implementação concluída; aceitação Docker pendente por indisponibilidade do daemon

## Ambiente observado

- Host Linux: 16 CPUs, 31 GiB de RAM e 232 GiB livres.
- Runtime local: Python 3.14.7; as imagens usam Python 3.12.
- scikit-learn 1.9.1, MLflow 3.17.2, Optuna 5.0.0, FastAPI 0.162.0 e SQLAlchemy 2.1.6.
- Snapshot: 20.640 linhas, SHA-256
  `8cd1f24964ff8b0decda0a7a2d2c4902e5cdaeb6a880a608e739390754891fe5`.

## Portões automatizados

| Portão | Resultado |
|---|---|
| `uv lock --check` | aprovado, 120 pacotes resolvidos |
| Ruff | aprovado |
| pytest sem o teste Docker stateful | 74 aprovados, 1 desmarcado, 2 avisos de dependências |
| quickstart automatizado | aprovado; 57 testes unitários/contratuais |
| Compose config | aprovado com `.env.example` |
| OpenAPI e JSON Schemas | aprovados |
| Dashboard e alertas Grafana | aprovados estaticamente e contra PostgreSQL real |
| Build das três imagens | pendente; daemon Docker não está em execução neste host |
| Persistência `down/up` | pendente pelo mesmo bloqueio do daemon |

O build foi tentado com `docker compose build trainer inference mlflow` e falhou antes de iniciar:
`dial unix /var/run/docker.sock: connect: no such file or directory`. O workflow CI mantém o build
das três imagens e o teste stateful como portões executáveis em um runner com Docker.

## Validação integrada nativa

Foi iniciado PostgreSQL 17 temporário com migrações Alembic, contas de privilégio mínimo, MLflow
Tracking/Registry e Optuna RDB. A execução
`00000000-0000-4000-8000-000000000103` treinou as cinco famílias em 13,44 s. O campeão foi
`random_forest`, versão `bb005f009ea6eab755eaaf27`, com:

| Métrica | Valor |
|---|---:|
| MAE | 0,3572307989202319 |
| MSE | 0,2756394940049377 |
| RMSE | 0,5250138036327594 |
| R² | 0,7931553452030103 |

A API carregou esse pacote, respondeu readiness 200 e produziu a previsão
`4,341883855367769` com a mesma versão do modelo e `environment_version=e2e-inference-v1`.

A execução final `00000000-0000-4000-8000-000000000105` terminou em 12,77 s como
`succeeded_no_promotion`, confirmando deduplicação. Ela persistiu cinco candidatos, cinco trials e
30 gráficos nas projeções estáveis. O Registry permaneceu com uma única versão e o alias/pointer do
campeão não mudou.

## PostgreSQL e Grafana

- As duas revisões Alembic foram aplicadas com sucesso.
- `pipeline_writer` gravou projeções idempotentes de runs, candidatos, trials, gráficos e inferência.
- Todas as queries versionadas do dashboard e dos alertas foram executadas como `grafana_reader`.
- Acesso direto de `grafana_reader` a `observability.training_runs` foi negado como esperado.
- O alerta de heartbeat trata `No Data` como alerta e usa janela de cinco minutos.

## Evidência semanal e rollback

O gerador produziu e validou uma evidência local contra o JSON Schema, vinculada à execução 105 e
ao campeão efetivo. SHA-256 da evidência:
`ec24201d9941f8a9fb5a84f9e904559ec09d059c7168805d98cb34383c5ab86e`.

Os testes de promoção cobrem staging inválido, falha após alteração do alias, compensação do alias,
troca atômica do ponteiro e exclusão mútua. Como não houve uma nova versão na execução final, o
resultado de rollback da evidência foi `not_required`.

## Pendência de aceitação

Para concluir T068 em um host com Docker, executar:

```bash
docker compose --env-file .env.example build trainer inference mlflow
RUN_DOCKER_PERSISTENCE_TEST=1 uv run pytest tests/integration/test_volume_persistence.py
```

Depois, seguir `quickstart.md` para subir a stack, confirmar readiness/previsão e registrar os
tempos/recursos dos contêineres. Nenhuma falha funcional conhecida permanece fora dessa validação
de runtime Docker.
