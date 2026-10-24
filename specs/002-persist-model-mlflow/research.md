# Research: Persistência e Catálogo de Modelos

## Unidade de durabilidade

**Decision**: Tratar `postgres-data`, `mlflow-artifacts` e `model-registry` como três partes de uma
unidade lógica. PostgreSQL preserva runs, Model Registry e ledger; o artifact store preserva objetos
publicados; o registry local preserva pacotes autônomos de serving.

**Rationale**: Arquivos isolados não recriam experimentos, versões ou aliases, que pertencem ao
backend store. O banco sem objetos deixa referências quebradas. O pacote local mantém serving e
rollback durante indisponibilidade temporária do tracking.

**Alternatives considered**: Um único volume de arquivos foi rejeitado por concorrência e perda do
Registry relacional; usar somente MLflow foi rejeitado porque a inferência já exige um pacote local.

Referências: [arquitetura MLflow](https://mlflow.org/docs/latest/self-hosting/architecture/overview/),
[artifact stores](https://mlflow.org/docs/latest/self-hosting/architecture/artifact-store/),
[volumes Docker](https://docs.docker.com/engine/storage/volumes/).

## Proxy de artefatos

**Decision**: Manter `--serve-artifacts` e `--artifacts-destination=/mlflow-artifacts`. Clientes usam
tracking HTTP e artifact URIs `mlflow-artifacts:`; nenhum cliente monta `/mlflow-artifacts`.

**Rationale**: O destination pertence ao filesystem do servidor. Com URI `file:` ou absoluto, o
cliente tenta escrever em seu próprio container, causando falha de permissão e acoplamento.

**Alternatives considered**: Montar o volume no trainer foi rejeitado por ampliar permissões; usar
`--default-artifact-root` junto do proxy foi rejeitado por misturar modos de acesso.

Referência: [MLflow proxied artifact access](https://mlflow.org/docs/latest/self-hosting/architecture/artifact-store/#use-mlflow-server-for-proxied-artifact-access).

## Experimento ativo e legado

**Decision**: Criar `house-price-training-v2` com artifact location proxy e manter experimentos
legados somente leitura. Pacotes íntegros são vinculados à run original ou recuperados no experimento
`house-price-model-reconciliation`, preservando IDs anteriores como tags.

**Rationale**: O artifact location é persistido na criação do experimento; trocar argumentos do
servidor não corrige runs antigas. Uma nova versão evita editar tabelas privadas do MLflow.

**Alternatives considered**: SQL direto no backend foi rejeitado por acoplamento e por não validar
objetos; reutilizar experimento com URI local foi rejeitado por continuar inacessível ao cliente.

## Identidade e registro idempotente

**Decision**: Usar `model_version` local como identidade canônica em tags de run e ModelVersion. Sob
advisory lock, pesquisar essa tag antes de `create_model_version`: uma correspondência íntegra é
reutilizada, zero cria uma versão e mais de uma ou checksums divergentes geram conflito.

**Rationale**: O número sequencial do MLflow pode mudar após restore e a API não oferece idempotency
key única. Lock, ledger e busca determinística evitam duplicação após crash.

**Alternatives considered**: `register_model()` cego foi rejeitado porque repetições criam versões;
usar somente o run ID foi rejeitado porque uma recuperação recebe novo ID.

Referências: [MLflow Client](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.client.html),
[PostgreSQL advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).

## Ledger próprio

**Decision**: Criar schema PostgreSQL `catalog` com entradas, reconciliações, itens, eventos e
solicitações de exclusão. A aplicação acessa MLflow exclusivamente pela API pública.

**Rationale**: O ledger fornece constraints únicas, fases duráveis da saga e tombstones mesmo quando
uma chamada MLflow falha. Tags continuam sendo a correlação visível, mas não substituem constraints.

**Alternatives considered**: Usar somente tags foi rejeitado pela janela entre criar versão e gravar
tags; gravar índice dentro do pacote foi rejeitado por violar imutabilidade.

## Manifesto v2 autossuficiente

**Decision**: O pacote v2 contém diretório de modelo em formato MLflow, parâmetros, métricas,
assinatura, código, dataset, ambiente, lockfile e checksums de todos os artefatos. IDs MLflow de
origem são históricos; o vínculo ativo permanece no ledger.

**Rationale**: O manifesto v1 não contém parâmetros nem um pacote MLflow completo e amarra uma versão
sequencial ao conteúdo imutável. O v2 permite republicar pelo proxy sem fingir o ID original.

**Alternatives considered**: Reescrever v1 foi rejeitado por alterar versão publicada; desserializar
automaticamente qualquer joblib legado foi rejeitado porque formatos pickle podem executar código.

Referência: [segurança da persistência scikit-learn](https://scikit-learn.org/stable/model_persistence.html#security-maintainability-limitations).

## Compatibilidade v1

**Decision**: Ler e validar v1 por adapter. Se run e artefato originais existirem, criar/reparar o
vínculo. Se estiverem ausentes, preservar o pacote e marcá-lo `unsupported`/`quarantined`; não
desserializar nem promover. Novo treinamento produz v2.

**Rationale**: Isso mostra modelos atuais quando a persistência completa existe e mantém segurança
quando a proveniência necessária à recuperação foi perdida.

**Alternatives considered**: Rejeitar todo v1 quebraria o histórico existente; promovê-lo sem
parâmetros e artifact format violaria FR-004 e a rastreabilidade constitucional.

## Saga de publicação

**Decision**: Persistir intenção no ledger, criar/reutilizar ModelVersion com estado `preparing`,
materializar pacote, preparar alias, substituir `current.json` com flush/fsync/replace e marcar
`approved`. Reconciliação conclui ou compensa fases interrompidas.

**Rationale**: Filesystem e MLflow não compartilham transação. Estados duráveis, ordem e compensação
impedem que publicação parcial apareça como campeão.

**Alternatives considered**: Rename isolado não cobre Registry; alias isolado não representa o
modelo realmente servido.

Referência: [Python `os.replace`](https://docs.python.org/3.12/library/os.html#os.replace).

## Autoridade do campeão

**Decision**: `current.json` é o commit point de serving, mas divergência com alias/ledger é conflito,
não reparo silencioso. Resolução explícita só pode ajustar o alias para o pacote íntegro servido; não
avança o ponteiro para uma versão descoberta.

**Rationale**: A inferência lê o volume. Escolher pelo alias poderia trocar o modelo sem validar os
bytes locais; escolher pelo timestamp ocultaria restore inconsistente.

**Alternatives considered**: Alias como verdade única e “mais recente vence” foram rejeitados por
risco de serving não auditado.

## Saúde e disponibilidade

**Decision**: `/health` verifica servidor/banco; `model-catalog check` realiza sonda profunda do
proxy, ledger, pacote e campeão. A inferência inicia pelo volume e não depende de MLflow/PostgreSQL
quando já existe pacote válido.

**Rationale**: Liveness não prova upload real, mas condicionar previsão ao tracking reduz
disponibilidade sem benefício. Falha do catálogo bloqueia mutações, não o último modelo carregado.

**Alternatives considered**: Sonda profunda em todo healthcheck foi rejeitada por gerar objetos e
carga; dependência rígida da inferência no MLflow foi rejeitada por acoplamento.

## Migração do backend MLflow

**Decision**: Executar `mlflow db upgrade` em serviço one-shot antes do servidor, com backup prévio e
mesma versão de client/server verificada por `/version`.

**Rationale**: O Model Registry exige backend de banco compatível; upgrade explícito separa mudança
de schema do startup do serviço.

**Alternatives considered**: Migração implícita no start foi rejeitada por dificultar rollback.

Referência: [MLflow backend stores](https://mlflow.org/docs/latest/tracking/backend-stores/).

## Remoção e volumes externos

**Decision**: Usar volumes externos com nomes estáveis. Exclusão de modelo é dry-run por padrão,
exige confirmação, cria tombstone, move para trash e bloqueia campeão/último modelo íntegro. Purga é
uma segunda operação. Destruição dos volumes exige comando administrativo separado.

**Rationale**: Compose deixa de remover estado por `down -v`; tombstones evitam ressuscitar versões
apagadas ao restaurar backup antigo.

**Alternatives considered**: Retenção automática foi rejeitada por remover rollback; volumes
gerenciados pelo Compose foram rejeitados porque `down -v` não informa o impacto por versão.

## Backup e automação semanal

**Decision**: Backup mantém os três dumps e os dois arquivos de volume. Após restore, o workflow
aplica migrações, inicia MLflow, reconcilia, verifica o campeão e inclui relatório/checksums na
evidência semanal antes do treino.

**Rationale**: Backups podem representar instantes diferentes. Reconciliação explícita impede nova
promoção quando a unidade lógica não converge e deixa evidência mesmo sem modelo novo.

**Alternatives considered**: Restore silencioso foi rejeitado por referências órfãs; apagar o lado
mais novo foi rejeitado por perda de dados.

