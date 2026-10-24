# Feature Specification: Persistência e Catálogo de Modelos

**Feature Branch**: `002-persist-model-mlflow`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "Permita que os dados de modelos presentes no volume do Docker sejam persistidos e mostrados no MLflow."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preservar modelos entre reinicializações (Priority: P1)

Como responsável pelo modelo, quero que modelos e seus registros permaneçam disponíveis quando o
ambiente conteinerizado for parado, iniciado novamente ou recriado, para não perder o resultado de
treinamentos válidos.

**Why this priority**: Sem persistência, o histórico experimental e o modelo aprovado deixam de ser
confiáveis, impedindo reprodução, auditoria e recuperação do serviço.

**Independent Test**: Pode ser testado salvando modelos de duas execuções, anotando suas identidades
e métricas, recriando os containers sem remover o armazenamento persistente e confirmando que os
mesmos registros e artefatos continuam consultáveis e recuperáveis.

**Acceptance Scenarios**:

1. **Given** duas execuções concluídas com modelos armazenados, **When** todos os containers são
   parados e iniciados novamente, **Then** os modelos, execuções, métricas, parâmetros e artefatos
   continuam disponíveis sem novo treinamento.
2. **Given** um modelo aprovado armazenado, **When** os containers são recriados preservando o volume,
   **Then** o mesmo modelo aprovado pode ser localizado, verificado e carregado.
3. **Given** que o armazenamento persistente está indisponível ou sem permissão de escrita, **When**
   uma execução tenta publicar um modelo, **Then** a publicação falha explicitamente, o modelo
   aprovado anterior é preservado e nenhum registro incompleto é apresentado como válido.

---

### User Story 2 - Consultar modelos no MLflow (Priority: P2)

Como responsável pelo modelo, quero visualizar no MLflow os modelos persistidos e os dados que
explicam sua origem e qualidade, para comparar execuções e identificar com segurança qual versão
está aprovada.

**Why this priority**: A persistência só produz valor operacional quando seus registros podem ser
encontrados, interpretados e relacionados aos artefatos corretos.

**Independent Test**: Pode ser testado concluindo uma execução e verificando, exclusivamente pela
interface de rastreamento, sua família de modelo, versão, estado, métricas, parâmetros, origem dos
dados, versão do código e artefatos disponíveis.

**Acceptance Scenarios**:

1. **Given** um treinamento concluído com sucesso, **When** o responsável consulta o MLflow, **Then**
   encontra a execução e seu modelo associados às métricas, parâmetros, dados, código, estado de
   promoção e artefatos correspondentes.
2. **Given** múltiplas versões persistidas, **When** o responsável consulta o catálogo, **Then**
   distingue candidatos, versões rejeitadas e o modelo aprovado sem depender dos nomes físicos dos
   arquivos.
3. **Given** uma execução falha antes de concluir a publicação, **When** o MLflow é consultado,
   **Then** a falha permanece auditável, mas seus artefatos parciais não aparecem como versão válida
   ou aprovada.

---

### User Story 3 - Reconciliar modelos existentes (Priority: P3)

Como operador, quero reconciliar os modelos que já estejam no volume com o catálogo de experimentos,
para que uma atualização do ambiente não torne invisível o histórico previamente armazenado.

**Why this priority**: A reconciliação protege os dados existentes durante a adoção da feature e
evita registros duplicados ou órfãos após recuperações.

**Independent Test**: Pode ser testado iniciando o ambiente com um conjunto conhecido de modelos
válidos já presente no volume e confirmando que cada modelo aparece uma única vez no catálogo, com
integridade e origem verificadas.

**Acceptance Scenarios**:

1. **Given** modelos válidos já existentes no volume e ausentes do catálogo, **When** a reconciliação
   é executada, **Then** cada modelo é associado a uma única entrada consultável, preservando sua
   identidade e proveniência disponíveis.
2. **Given** um modelo já reconciliado, **When** a reconciliação é repetida, **Then** nenhum registro
   ou versão duplicada é criado.
3. **Given** um arquivo órfão, incompleto ou com integridade inválida, **When** a reconciliação é
   executada, **Then** ele é isolado da seleção e da inferência, e o diagnóstico fica consultável.

### Edge Cases

- O armazenamento contém artefatos de modelo, mas seus metadados estão ausentes ou incompletos.
- Os metadados referenciam um artefato que não existe mais no armazenamento persistente.
- O volume está cheio, somente para leitura, indisponível ou com permissões incompatíveis.
- Uma publicação é interrompida depois da escrita do artefato, mas antes da confirmação do registro.
- Duas execuções tentam publicar ou reconciliar a mesma identidade de modelo simultaneamente.
- Um modelo existente usa uma versão anterior do manifesto ou não possui checksum.
- Um backup antigo do volume é restaurado junto com metadados mais recentes.
- A interface de consulta está temporariamente indisponível enquanto os dados persistentes continuam
  íntegros.
- A remoção explícita do volume é solicitada pelo operador.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema MUST armazenar de forma persistente os artefatos de cada modelo publicado e
  os registros necessários para localizar, interpretar e auditar esse modelo.
- **FR-002**: Os modelos, execuções, métricas, parâmetros, estados e vínculos entre esses dados MUST
  sobreviver à parada, inicialização e recriação dos containers quando o volume não for removido.
- **FR-003**: Todo modelo publicado com sucesso MUST estar associado a exatamente uma execução
  rastreável e MUST ficar consultável no MLflow.
- **FR-004**: Para cada modelo consultável, o sistema MUST apresentar identidade imutável, família,
  versão, horário, estado da execução, decisão de promoção, parâmetros, métricas, referência dos
  dados, versão do código e relação de artefatos.
- **FR-005**: Cada modelo persistido MUST possuir um manifesto verificável que relacione sua
  identidade, execução, artefatos e checksums antes de permitir carregamento ou promoção.
- **FR-006**: A publicação MUST ser atômica do ponto de vista do usuário: um modelo somente pode
  aparecer como válido depois que seu artefato e seus metadados obrigatórios estiverem confirmados.
- **FR-007**: O sistema MUST reconciliar modelos válidos que já estejam presentes no volume e ainda
  não estejam visíveis no MLflow, sem alterar sua identidade original quando ela puder ser
  comprovada.
- **FR-008**: A reconciliação MUST ser idempotente e MUST impedir registros, versões ou associações
  duplicadas para o mesmo modelo e execução.
- **FR-009**: Artefatos ausentes, parciais, órfãos, incompatíveis ou com checksum inválido MUST ser
  impedidos de promoção e inferência, sem afetar o último modelo aprovado íntegro, e MUST produzir
  diagnóstico rastreável.
- **FR-010**: O modelo marcado como aprovado MUST apontar para uma versão persistida, visível no
  MLflow e recuperável com integridade comprovada.
- **FR-011**: Versões publicadas MUST permanecer imutáveis; uma nova publicação com conteúdo ou
  identidade diferente MUST criar uma nova versão, sem sobrescrever o histórico anterior.
- **FR-012**: Modelos e registros MUST ser conservados até uma operação explícita de remoção; parar ou
  recriar containers não constitui autorização para removê-los.
- **FR-013**: Uma remoção explícita MUST informar previamente quais versões e vínculos serão afetados
  e MUST impedir a exclusão silenciosa do modelo aprovado em uso.
- **FR-014**: Na inicialização, o sistema MUST verificar a disponibilidade, a capacidade de escrita e
  a consistência básica do armazenamento persistente, expondo estado não saudável quando essas
  condições impedirem publicação ou recuperação segura.
- **FR-015**: Publicações e reconciliações concorrentes MUST preservar uma única identidade por
  modelo e execução e MUST deixar um estado final determinístico.
- **FR-016**: Falhas temporárias na interface do MLflow MUST NOT remover nem invalidar dados já
  persistidos; quando a interface voltar, os registros íntegros MUST ficar novamente consultáveis.
- **FR-017**: Credenciais, tokens e segredos MUST NOT ser gravados nos artefatos, manifestos,
  parâmetros, métricas ou diagnósticos dos modelos.
- **FR-018**: A persistência e a reconciliação MUST registrar eventos correlacionáveis contendo a
  execução, a versão do modelo, a operação realizada, o resultado e o horário, sem incluir dados
  sensíveis.

### Scope Boundaries

- Esta feature inclui persistência local dos artefatos e metadados de modelos, exibição no MLflow,
  verificação de integridade e reconciliação dos modelos já presentes no volume.
- Esta feature não inclui replicação para armazenamento remoto, recuperação após remoção explícita do
  volume, definição de política de backup externo nem implantação em nuvem.
- Métricas operacionais no Grafana permanecem sob a feature anterior; esta feature não substitui o
  MLflow pelo Grafana como catálogo de experimentos e modelos.
- O treinamento e os critérios de promoção permanecem os definidos pela feature
  `001-train-container-metrics`.

### Key Entities *(include if feature involves data)*

- **Modelo persistido**: Artefato imutável de regressão identificado por versão, checksum, formato,
  execução de origem e estado de integridade.
- **Registro de execução**: Histórico consultável que relaciona modelo, parâmetros, métricas, dados,
  código, horários, resultado e decisão de promoção.
- **Manifesto de modelo**: Registro verificável que vincula a identidade do modelo aos artefatos e
  metadados obrigatórios usados para auditoria e recuperação.
- **Volume de modelos**: Armazenamento persistente cujo ciclo de vida é independente dos containers e
  que conserva os artefatos durante reinicializações e recriações.
- **Entrada do catálogo**: Representação do modelo e de sua execução no MLflow, incluindo estado,
  versão e localização verificável dos artefatos.
- **Resultado de reconciliação**: Evidência de associação, preservação, rejeição ou isolamento de um
  item encontrado no volume.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Em cinco ciclos consecutivos de parada, inicialização e recriação dos containers sem
  remoção do volume, 100% dos modelos e registros previamente publicados permanecem consultáveis e
  passam na verificação de integridade.
- **SC-002**: 100% dos treinamentos concluídos com publicação bem-sucedida aparecem no catálogo com
  todos os campos obrigatórios de FR-004 em até dois minutos.
- **SC-003**: Um responsável consegue identificar o modelo aprovado, sua execução, suas métricas e
  seus artefatos em até dois minutos usando somente a interface de rastreamento.
- **SC-004**: Em uma reconciliação de referência com pelo menos dez modelos existentes, 100% dos
  modelos íntegros aparecem exatamente uma vez e 100% dos itens inválidos são impedidos de promoção
  e inferência.
- **SC-005**: Cinco repetições da reconciliação sobre o mesmo conteúdo produzem a mesma quantidade de
  modelos, versões e associações, sem duplicações.
- **SC-006**: Em testes de interrupção em cada etapa da publicação, 100% das tentativas deixam o
  catálogo em um estado no qual o modelo está completamente válido ou explicitamente falho, nunca
  parcialmente aprovado.
- **SC-007**: Em 100% dos testes com armazenamento cheio, somente para leitura ou indisponível, a
  falha é sinalizada e o último modelo aprovado íntegro permanece inalterado.
- **SC-008**: 100% dos modelos marcados como aprovados podem ser recuperados a partir de sua entrada
  no catálogo e correspondem ao checksum registrado.
- **SC-009**: Nenhum segredo conhecido inserido pelos testes aparece nos artefatos, manifestos,
  campos de catálogo ou diagnósticos examinados.

## Assumptions

- Docker e MLflow são restrições fornecidas pelo usuário e pela constituição; esta especificação
  descreve os resultados esperados sem prescrever a organização interna dos serviços.
- O volume já usado para armazenar modelos é a fonte inicial para reconciliação; a existência de um
  arquivo isolado não é suficiente para considerá-lo um modelo válido sem identidade e integridade
  verificáveis.
- O armazenamento de metadados necessário para o catálogo possui persistência compatível com o ciclo
  de vida do volume de artefatos; preservar apenas os arquivos não satisfaz esta feature.
- A remoção explícita do volume representa intenção de excluir dados e fica fora da garantia de
  persistência. Reinicialização e recriação sem remoção do volume não representam essa intenção.
- O acesso à interface do MLflow continua restrito ao ambiente local conforme as regras de exposição
  definidas para o projeto.
- A política de retenção padrão é conservar todas as versões até uma remoção explícita e protegida.
- Modelos legados sem evidência suficiente de origem ou integridade são preservados para diagnóstico,
  mas não são automaticamente promovidos nem usados em inferência.

