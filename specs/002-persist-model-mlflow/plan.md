# Implementation Plan: Persistência e Catálogo de Modelos

**Branch**: `002-persist-model-mlflow` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-persist-model-mlflow/spec.md`

## Summary

Preservar como unidade lógica os metadados do MLflow no PostgreSQL, os artefatos servidos pelo
MLflow e os pacotes imutáveis usados pela inferência. O trainer continuará enviando artefatos pelo
tracking server HTTP, sem montar o volume interno do MLflow. Um ledger próprio no PostgreSQL
vinculará a identidade estável do pacote à run e à versão ativa no MLflow. Uma CLI idempotente
verificará, reconciliará e removerá versões protegidas sob o mesmo advisory lock da promoção,
recuperando modelos íntegros sem promover automaticamente itens descobertos.

## Technical Context

**Language/Version**: Python 3.12 (compatibilidade declarada: 3.12–3.14)

**Primary Dependencies**: MLflow 3.17.2, Pydantic 2.x, SQLAlchemy 2.x, psycopg 3.x, joblib 1.x,
scikit-learn 1.x, Docker Compose v2

**Storage**: PostgreSQL 17 em `postgres-data` para MLflow e ledger `catalog`; artifact store servido
pelo MLflow em `mlflow-artifacts`; pacotes imutáveis em `model-registry`

**Testing**: pytest 8/9, testes unitários, contratos JSON/CLI/MLflow, integração PostgreSQL/MLflow e
aceitação stateful com Docker Compose

**Target Platform**: Host Linux local com Docker Engine/Compose; imagens Linux não-root; Azure for
Students continua como incremento futuro

**Project Type**: Pipeline MLOps conteinerizada com job batch, CLI operacional e serviço HTTP de
inferência

**Performance Goals**: Modelo publicado visível no catálogo em até 2 minutos; identificação do
campeão e de sua linhagem em até 2 minutos; cinco ciclos de recriação sem perda

**Constraints**: Sem montar `mlflow-artifacts` no trainer; uploads pelo tracking server; versões
imutáveis; troca atômica no mesmo filesystem; inferência somente leitura; UIDs não-root; 10 GiB no
perfil local; remoção explícita dos volumes fora da garantia de recuperação

**Scale/Scope**: Dataset California Housing, cinco famílias por execução, histórico local completo,
reconciliação de pelo menos dez modelos por cenário de aceite e uma mutação de catálogo por vez

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

### Antes da pesquisa

| Princípio/portão | Resultado | Evidência |
|---|---|---|
| Experimentos rastreáveis e reproduzíveis | PASS | Metadados, parâmetros, métricas, dados, código, manifestos e artefatos ficam vinculados no MLflow e no ledger. |
| Dados externos confiáveis | PASS — não aplicável | A feature não adquire nem altera fontes externas. |
| Automação semanal segura | PASS | Restore semanal executa reconciliação idempotente e arquiva relatório/checksums. |
| Contêiner como unidade de entrega | PASS | Imagens não-root, healthchecks e volumes persistentes; nuvem explicitamente fora do escopo. |
| Observabilidade operacional e de modelo | PASS | Eventos estruturados correlacionam operação, run e versão; projeções Grafana existentes permanecem. |
| MLflow e configuração externa | PASS | MLflow segue oficial; URIs, nomes e paths são configuráveis, sem segredos em imagem. |
| CI e portões de qualidade | PASS | Contratos, corrupção, concorrência, persistência, migrações e imagens entram no CI. |
| Promoção e rollback seguros | PASS | Saga persistente, lock compartilhado, commit point local e compensação preservam o campeão anterior. |

Não há violações que exijam exceção constitucional.

### Depois do desenho da Fase 1

**Resultado: PASS.** O desenho separa pacote imutável, ledger transacional, objetos MLflow e ponteiro
de serving; os contratos impedem publicação parcial, promoção implícita e exclusão do campeão; o
quickstart comprova persistência, consulta, reconciliação, corrupção e restore inconsistente. A
execução semanal passa a registrar a recuperabilidade. Nenhuma decisão introduz serviço externo,
credencial em artefato ou dependência incompatível com o ambiente local.

## Architecture and Data Flow

```text
trainer / model-catalog CLI
        │ tracking e artifact upload por HTTP
        ▼
MLflow server ───────────────► mlflow-artifacts volume
        │ runs, registry, aliases
        ▼
PostgreSQL mlflow database ──► postgres-data volume
        ▲
        │ catalog ledger + advisory lock
        │
trainer / model-catalog CLI ─► model-registry volume
                               ├── models/<model_version>/
                               ├── .staging/ e .trash/
                               └── current.json
                                         │ read-only
                                         ▼
                                      inference
```

### Responsabilidades

- **Pacote imutável**: autoridade sobre bytes, checksums, proveniência e identidade estável.
- **MLflow**: interface oficial para runs, métricas, parâmetros, artefatos, versões e alias.
- **Ledger `catalog`**: idempotência, fases da saga, vínculos atuais, reconciliações, conflitos,
  tombstones e eventos append-only; não consulta tabelas internas do MLflow.
- **`current.json`**: commit point do modelo efetivamente servido. Divergência com o alias é conflito
  explícito; nenhuma regra escolhe silenciosamente pelo timestamp.

## Publication Saga

1. Validar configuração, capacidade de escrita, espaço, tracking server e artifact proxy.
2. Criar runs e publicar parâmetros, métricas, plots e modelo pelo tracking HTTP. O experimento deve
   usar URI `mlflow-artifacts:`, nunca `file:` ou `/mlflow-artifacts`.
3. Gerar manifesto v2 e pacote temporário com o diretório MLflow completo, parâmetros, métricas,
   plots, lockfile e checksums de todos os arquivos; validar antes de mover.
4. Sob advisory lock, gravar intenção `registering` no ledger. Buscar versão por tag de identidade;
   reutilizar exatamente uma correspondência íntegra, criar se não existir e falhar se houver
   conflito/duplicidade.
5. Mover o pacote para `models/<model_version>` no mesmo filesystem e marcar vínculo `registered`.
6. Para promoção, preparar o alias, gravar `current.json` com flush/fsync/replace/fsync de diretório e
   então marcar a versão `approved`. Falha conclui ou compensa a saga na reconciliação seguinte.
7. A inferência lê somente pacote e ponteiro; tracking indisponível não derruba o modelo já carregado.

## Reconciliation Flow

1. Adquirir o lock global compartilhado por promoção, reconciliação e remoção.
2. Varrer apenas `models/<model_version>`; ignorar staging, quarantine e trash; recusar symlinks e
   caminhos que escapem do volume.
3. Validar schema, conjunto de arquivos e checksums sem desserializar o modelo.
4. Comparar pacote com tombstones, ledger e versões encontradas pela API pública do MLflow.
5. Reutilizar vínculo íntegro; criar uma versão ausente quando a run original ainda existe.
6. Se a run não existir e o pacote v2 for autossuficiente, criar run no experimento de recuperação,
   enviar o diretório MLflow pelo proxy e registrar uma única versão com IDs de origem em tags.
7. Pacote v1 só é recuperável quando a run/artifact original existe. Sem parâmetros ou formato MLflow
   completo, ele permanece preservado e `quarantined`, sem desserialização automática.
8. Alias e `current.json` divergentes geram conflito. Um comando explícito de resolução pode reparar
   o alias para o pacote íntegro efetivamente servido; nunca avança o ponteiro automaticamente.
9. Registrar relatório e eventos. Resultado parcial retorna código não zero e não invalida modelos
   íntegros existentes.

## MLflow Conventions

- Experimento ativo configurável, padrão `house-price-training-v2`, criado com artifact location
  proxy. Experimentos legados permanecem somente leitura.
- Experimento `house-price-model-reconciliation` guarda operações de recuperação.
- Registered Model permanece `house-price-regressor`; alias operacional permanece `champion`.
- Identidade canônica: tag `catalog.model_version`; tags também incluem checksums, training run,
  dataset, origem, integridade e estado de publicação.
- Novas versões são criadas pela API do cliente com tags iniciais; `except Exception` não pode ser
  usado para interpretar indisponibilidade como recurso ausente.
- Um serviço one-shot executa `mlflow db upgrade` antes do servidor após backup e usa a mesma versão
  de cliente/servidor.
- Trainer, inferência e CLI não montam `mlflow-artifacts`; somente o servidor MLflow escreve nele.

## Retention and Protected Removal

- Os três volumes passam a ter nomes externos estáveis; `docker compose down -v` não os remove.
- Um comando administrativo cria/verifica volumes antes do primeiro `up` e é o único caminho
  documentado para destruição coordenada.
- `model-catalog delete` é dry-run por padrão, mostra pacote, ledger, versão e referências; aplicação
  exige confirmação da versão e recusa campeão, alias champion, último modelo íntegro ou operação
  concorrente.
- A exclusão cria tombstone e move o pacote atomicamente para `.trash`; remover a versão MLflow vem
  depois. Purga física exige comando e confirmação separados.
- Um pacote tombstonado que reaparece em backup antigo é diagnosticado e não ressuscitado.

## Failure and Health Rules

- Preflight do trainer/reconciliador testa read/write/rename no model registry e upload/download
  temporário pelo proxy, sem deixar versão de modelo.
- Compose inclui jobs one-shot `mlflow-migrate` e `catalog-reconcile`. O primeiro atualiza somente o
  backend MLflow; o segundo aplica migrações próprias, verifica os volumes e reconcilia após startup
  ou restore. O trainer depende da conclusão saudável desse preflight, mas a inferência não.
- Health do MLflow valida processo/banco; verificação profunda fica na CLI para não poluir runs.
- Artifact store indisponível bloqueia publicação, não serving do campeão local.
- Restore mais novo de um lado nunca apaga automaticamente o outro; produz conflito ou recuperação.
- Inference não depende de MLflow/PostgreSQL para iniciar com pacote íntegro, mas reporta degradação
  de observabilidade separadamente.
- Eventos nunca contêm URLs com senha, payloads ou segredos.

## Requirement Coverage

| Requisitos | Decisão de desenho |
|---|---|
| FR-001–FR-004 | Unidade de três stores, manifesto v2, ledger e convenções MLflow preservam e exibem modelo, run, parâmetros, métricas e linhagem. |
| FR-005–FR-006 | Checksums completos e saga com intenção, validação, commit point e compensação impedem publicação parcial. |
| FR-007–FR-008 | CLI, identidade canônica, constraints, busca por tags e lock tornam a reconciliação de conteúdo existente idempotente. |
| FR-009–FR-010 | Estados de integridade/quarentena e invariantes de champion protegem inferência e último campeão. |
| FR-011–FR-013 | Pacotes imutáveis, retenção padrão, volumes externos, impacto, confirmação, trash e tombstone protegem histórico e remoção. |
| FR-014–FR-016 | Jobs de startup, probes profundos, lock global e serving desacoplado cobrem saúde, concorrência e indisponibilidade da interface. |
| FR-017–FR-018 | Redação de segredos e ledger append-only fornecem eventos correlacionáveis e seguros. |

## Project Structure

### Documentation (this feature)

```text
specs/002-persist-model-mlflow/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── catalog-cli.md
│   ├── deletion-impact.schema.json
│   ├── mlflow-catalog.md
│   ├── model-package-manifest-v2.schema.json
│   └── reconciliation-report.schema.json
└── tasks.md                  # criado posteriormente por $speckit-tasks
```

### Source Code (repository root)

```text
compose.yaml
.env.example
docker/
├── mlflow.Dockerfile
└── trainer.Dockerfile

migrations/versions/
└── 003_model_catalog.py

src/house_price/
├── catalog/
│   ├── __init__.py
│   ├── cli.py
│   ├── models.py
│   ├── repository.py
│   ├── reconciliation.py
│   └── removal.py
├── registry/
│   ├── atomic.py
│   ├── loader.py
│   ├── manifest.py
│   ├── pointer.py
│   └── promotion.py
├── tracking/mlflow_client.py
├── training/
│   ├── pipeline.py
│   └── tracking.py
└── settings.py

tests/
├── contract/
├── integration/
│   ├── test_catalog_reconciliation.py
│   ├── test_promotion_crash_recovery.py
│   ├── test_storage_permissions.py
│   └── test_volume_persistence.py
└── unit/
    ├── test_catalog_models.py
    ├── test_reconciliation.py
    └── test_registry_atomic.py

.github/workflows/{ci.yml,weekly-training.yml}
README.md
docs/operations.md
```

**Structure Decision**: Manter o projeto Python único. O novo domínio `catalog` concentra ledger,
CLI, reconciliação e remoção; `registry` continua responsável pelo pacote usado em serving;
`tracking` encapsula somente APIs públicas do MLflow. A separação evita acoplar inferência ao
tracking server e permite recuperar catálogo sem treinar novamente.

## Phase Outputs

- [research.md](research.md): decisões de durabilidade, proxy, saga, identidade, legado e remoção.
- [data-model.md](data-model.md): entidades, relações, invariantes e transições.
- [contracts/](contracts/): manifesto v2, relatório, impacto de exclusão, CLI e convenções MLflow.
- [quickstart.md](quickstart.md): validação ponta a ponta.

## Complexity Tracking

Nenhuma violação constitucional ou estrutura adicional que exija justificativa.

