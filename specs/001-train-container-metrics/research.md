# Research: Treinamento Conteinerizado com Métricas

## Runtime e dependências

**Decision**: Adotar Python 3.12, MLflow 3.x, Optuna 5.x, scikit-learn 1.9.x e versões
compatíveis de FastAPI, Pydantic, pandas, NumPy, SciPy, psycopg e SQLAlchemy. A implementação deve
fixar versões exatas e hashes em lockfile compartilhado pelas imagens de treino e inferência.

**Rationale**: Python 3.12 está na interseção suportada pelas linhas atuais das bibliotecas e evita
carregar modelos com versões diferentes de scikit-learn, NumPy ou SciPy. O lockfile torna a imagem e
o modelo reproduzíveis.

**Alternatives considered**: Usar dependências sem pinagem foi rejeitado por impedir reprodução;
usar a versão Python mais recente sem verificar compatibilidade foi rejeitado por risco operacional.

Referências: [MLflow](https://www.mlflow.org/docs/latest/genai/getting-started/connect-environment/),
[Optuna](https://optuna.readthedocs.io/en/stable/installation.html),
[scikit-learn](https://scikit-learn.org/stable/install.html).

## Topologia local

**Decision**: Usar Docker Compose com quatro serviços: `postgres`, `mlflow`, `trainer` e
`inference`. `trainer` é um job batch iniciado sob demanda ou pela automação semanal; `inference`
permanece ativo. Grafana continua externo. Os volumes nomeados são `postgres-data`,
`mlflow-artifacts` e `model-registry`.

**Rationale**: Os componentes têm ciclos de vida e permissões diferentes. Health checks e
dependências condicionais evitam iniciar treino ou inferência antes dos serviços necessários. Os
volumes sobrevivem à recriação de contêineres.

**Alternatives considered**: Um único contêiner foi rejeitado por misturar job batch e serviço;
bind mounts foram rejeitados como contrato principal por serem menos portáveis; incluir Grafana no
Compose viola a clarificação de que ele é externo.

Referências: [ordem de inicialização](https://docs.docker.com/compose/how-tos/startup-order),
[volumes](https://docs.docker.com/reference/compose-file/volumes/),
[serviços Compose](https://docs.docker.com/reference/compose-file/services/).

## Rastreamento MLflow

**Decision**: Executar um MLflow Tracking Server com backend PostgreSQL e artifact store no volume
`mlflow-artifacts`. Cada pipeline cria uma run pai, cada família cria uma run filha e cada trial
Optuna cria uma run aninhada. Apenas o melhor trial de cada família salva um artefato de modelo; os
cinco finalistas são avaliados no holdout. O vencedor é registrado como `house-price-regressor` e
recebe o alias `champion` somente após todos os portões.

**Rationale**: Runs aninhadas mantêm a relação pipeline → família → trial sem perder parâmetros e
métricas. O Registry preserva versão, assinatura e linhagem, enquanto o alias simplifica rollback.

**Alternatives considered**: Autolog puro foi rejeitado por gerar artefatos excessivos e reduzir o
controle da hierarquia; backend somente em arquivos foi rejeitado por limitar concorrência e
registro de modelos.

Referências: [tuning com MLflow](https://mlflow.org/docs/latest/ml/getting-started/hyperparameter-tuning),
[Model Registry](https://mlflow.org/docs/latest/model-registry),
[artifact stores](https://mlflow.org/docs/latest/self-hosting/architecture/artifact-store/).

## Otimização Optuna sem vazamento

**Decision**: Usar `RDBStorage` em PostgreSQL, `TPESampler` com seed fixa e `n_jobs=1`. Cada família
tem estudo e espaço de busca versionados; regressão linear é um candidato determinístico de trial
único. O objetivo é RMSE médio de validação cruzada de cinco folds apenas sobre o conjunto de treino.
O holdout fixo é usado uma única vez por finalista para MAE, MSE, RMSE e R².

**Rationale**: O estudo persistente permite retomada idempotente. Seed fixa e execução serial
atendem a reprodutibilidade. Manter o holdout fora da otimização evita vazamento de informação.

**Alternatives considered**: `InMemoryStorage`, trials paralelos e otimização direta no holdout foram
rejeitados por perda de retomada, não determinismo e avaliação enviesada, respectivamente.

Referências: [RDBStorage](https://optuna.readthedocs.io/en/stable/reference/generated/optuna.storages.RDBStorage.html),
[create_study](https://optuna.readthedocs.io/en/stable/reference/generated/optuna.create_study.html),
[reprodutibilidade](https://optuna.readthedocs.io/en/stable/faq.html).

## Dataset e avaliação

**Decision**: Gerar durante o build um snapshot Parquet do California Housing e um manifesto com
fonte, versão, schema, quantidade de linhas e SHA-256; ambos ficam somente na imagem `trainer`.
Validar 20.640 linhas, oito features esperadas, target, tipos numéricos e ausência de valores
ausentes ou não finitos. Usar split holdout de 33% com seed 42, preservado para todas as famílias.

**Rationale**: A imagem executa sem internet e vincula código e dados. Um único split torna a
comparação justa e mantém compatibilidade com o projeto original.

**Alternatives considered**: Download em toda execução e cache implícito foram rejeitados por
dependência externa e identidade de dados fraca; montar dataset do host contradiz a decisão de
embuti-lo na imagem.

## Persistência e promoção do campeão

**Decision**: O trainer materializa o pacote MLflow completo do vencedor no volume
`model-registry`, em `models/<model_version>/`, com modelo, `manifest.json`, `metrics.json` e gráficos.
Ele valida o staging e move o diretório no mesmo filesystem. Sob lock, altera o alias MLflow e então
substitui `current.json` atomicamente; falha no ponteiro restaura o alias anterior. A inferência exige
concordância entre alias, manifesto e ponteiro. `trainer` monta leitura/escrita e `inference` somente
leitura. Um lock transacional no PostgreSQL serializa promoções.

**Rationale**: Versões imutáveis e ponteiro atômico impedem leitura parcial, preservam rollback e
satisfazem o requisito explícito de manter o melhor modelo em volume Docker.

**Alternatives considered**: Sobrescrever um arquivo único, usar apenas `latest` ou guardar o modelo
somente no MLflow foram rejeitados por corrupção parcial, perda de identidade ou descumprimento do
requisito do volume.

Referências: [os.replace](https://docs.python.org/3.12/library/os.html#os.replace),
[persistência de modelos](https://scikit-learn.org/stable/model_persistence.html).

## Métricas para Grafana

**Decision**: Usar a mesma instância PostgreSQL com bancos separados para `mlflow` e `optuna` e o
schema `observability` no banco principal. O trainer projeta resultados e a inferência agrega saúde, volume, erros e latência
por janela, sem payloads. Grafana consulta somente views estáveis com `grafana_reader` read-only. A
conexão local é publicada em `127.0.0.1`. Alertas versionados cobrem falha semanal, indisponibilidade
e violação dos gates de qualidade.

**Rationale**: PostgreSQL é uma fonte nativa do Grafana. Uma projeção própria evita acoplamento ao
schema interno e migrável do MLflow, e a conta somente leitura limita dano de consultas externas.

**Alternatives considered**: Consultar tabelas internas do MLflow foi rejeitado por acoplamento;
Prometheus com Pushgateway foi rejeitado por adicionar serviços e gestão de séries obsoletas;
SQLite foi rejeitado por concorrência e controle de acesso limitados.

Referências: [fonte PostgreSQL](https://grafana.com/docs/grafana/latest/datasources/postgres/),
[configuração segura](https://grafana.com/docs/grafana/latest/datasources/postgres/configure/),
[limites do Pushgateway](https://prometheus.io/docs/practices/pushing/).

## Gráficos e artefatos

**Decision**: Salvar como artefatos MLflow e no pacote do campeão: previsto versus observado,
resíduos, distribuição de erros, importância ou coeficientes de features quando suportados, histórico
da otimização e importância de hiperparâmetros. Versionar dashboard Grafana com MAE/MSE/RMSE/R²,
comparação de candidatos/execuções, convergência, duração, promoção, saúde, volume, erros e latência.

**Rationale**: Os artefatos explicam uma execução específica; o Grafana apresenta evolução temporal
e operação. A separação evita tentar usar Grafana como repositório de imagens estáticas.

**Alternatives considered**: Guardar somente números foi rejeitado por limitar diagnóstico; guardar
gráficos apenas no volume do campeão ocultaria execuções rejeitadas.

Referências: [visualizações Optuna](https://optuna.readthedocs.io/en/stable/reference/visualization/index.html),
[MLflow log_figure](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.html).

## Serviço de inferência

**Decision**: Expor HTTP com FastAPI: liveness, readiness, metadados do modelo e predição em lotes de
1 a 100 instâncias. A entrada contém exatamente as oito features do California Housing. O serviço
carrega o campeão no startup e observa `current.json`; somente troca a referência em memória após
validar pacote, checksum e assinatura, mantendo o campeão anterior em erro.

**Rationale**: Contrato tipado fornece validação e OpenAPI. Separar liveness de readiness representa
corretamente o processo vivo sem modelo válido.

**Alternatives considered**: Recarregar por requisição foi rejeitado por latência; reiniciar sempre o
serviço após promoção foi rejeitado por indisponibilidade desnecessária.

Referências: [response models](https://fastapi.tiangolo.com/tutorial/response-model/),
[lifespan](https://fastapi.tiangolo.com/advanced/events/).

## Segurança e testes

**Decision**: Executar imagens com UID/GID explícitos não-root, sem capabilities adicionais nem
socket Docker; usar rede interna e secrets/variáveis fora das imagens. Cobrir testes unitários,
contratos OpenAPI/SQL/manifesto, integração Compose, interrupção durante promoção, concorrência,
persistência após restart e treino sem egress.

**Rationale**: Menor privilégio reduz superfície de ataque; testes de falha comprovam que o último
campeão permanece utilizável.

**Alternatives considered**: Rodar como root e montar volume do campeão como escrita na inferência
foram rejeitados por violar menor privilégio e permitir alteração acidental.

Referências: [Docker build best practices](https://docs.docker.com/build/building/best-practices/),
[Dockerfile USER](https://docs.docker.com/reference/dockerfile/#user).
