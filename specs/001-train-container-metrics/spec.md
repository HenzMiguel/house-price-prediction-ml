# Feature Specification: Treinamento Conteinerizado com Métricas

**Feature Branch**: `001-train-container-metrics`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "treine o modelo com os dados presentes no dataset do repositório e coloque um container Docker; adicione métricas de regressão no Grafana."

## Clarifications

### Session 2026-10-24

- Q: Esta feature deve incluir a implantação do contêiner na Azure for Students ou encerrar na execução local? → A: Manter somente execução local e registrar a implantação Azure como uma feature futura.
- Q: O que deve iniciar pelo procedimento local conteinerizado desta feature? → A: Treinamento, previsão e armazenamento de métricas ficam conteinerizados; apenas o Grafana é externo.
- Q: Como o dataset California Housing deve ser disponibilizado para que os treinamentos locais sejam reproduzíveis? → A: Incluir um snapshot versionado do dataset diretamente na imagem de treinamento.
- Q: Quais modelos de regressão devem ser treinados e comparados em cada execução? → A: Comparar regressão linear, Ridge, Lasso, árvore de decisão e floresta aleatória.
- Q: Qual regra deve escolher o vencedor entre os modelos que passaram pelos limites mínimos de qualidade? → A: Menor RMSE; desempate por menor MAE e depois maior R².

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Treinar e avaliar o modelo (Priority: P1)

Como responsável pelo modelo, quero executar um treinamento reproduzível com o dataset de preços de
imóveis referenciado pelo repositório para obter um modelo avaliado e apto ou não apto para uso.

**Why this priority**: O modelo treinado e sua avaliação são a base de todos os demais resultados da
feature.

**Independent Test**: Pode ser testado iniciando uma execução com o dataset válido e verificando se
ela termina com um artefato de modelo, identificação dos dados, parâmetros e métricas MAE, MSE, RMSE
e R², além de uma decisão explícita de aprovação ou rejeição.

**Acceptance Scenarios**:

1. **Given** que o dataset referenciado está disponível e passa nas validações, **When** o responsável
   inicia o treinamento, **Then** a execução avalia os cinco tipos de modelo, registra as quatro
   métricas de cada candidato e produz uma decisão de qualidade rastreável.
2. **Given** que o dataset está ausente, vazio ou incompatível com o esquema esperado, **When** o
   treinamento é iniciado, **Then** a execução falha antes de treinar, informa a causa e não substitui
   o último modelo válido.
3. **Given** que um novo modelo não atinge o limite mínimo de qualidade, **When** sua avaliação é
   concluída, **Then** ele é registrado como rejeitado e o modelo aprovado anteriormente permanece
   disponível.
4. **Given** uma imagem de treinamento válida e ausência de acesso à internet, **When** o responsável
   inicia o treinamento, **Then** o snapshot incluído na imagem é validado e a execução prossegue sem
   baixar dados.

---

### User Story 2 - Executar o modelo de forma portátil (Priority: P2)

Como operador, quero iniciar um ambiente local conteinerizado para obter previsões sem depender da
configuração manual do ambiente de desenvolvimento.

**Why this priority**: O ambiente portátil torna o resultado do treinamento utilizável e verificável
em ambientes consistentes.

**Independent Test**: Pode ser testado iniciando o ambiente local conteinerizado em uma máquina limpa,
consultando sua saúde e solicitando uma previsão com um imóvel válido.

**Acceptance Scenarios**:

1. **Given** um modelo aprovado e um ambiente local conteinerizado versionado, **When** o operador o
   inicia, **Then** seus componentes ficam saudáveis e identificam a versão do modelo carregado.
2. **Given** uma solicitação com todos os atributos válidos, **When** uma previsão é solicitada,
   **Then** o usuário recebe um valor numérico de preço e a versão do modelo utilizada.
3. **Given** atributos ausentes, desconhecidos ou fora dos tipos aceitos, **When** uma previsão é
   solicitada, **Then** ela é recusada com uma mensagem que identifica os campos problemáticos.

---

### User Story 3 - Acompanhar qualidade da regressão (Priority: P3)

Como responsável pelo modelo, quero consultar um painel com o histórico das métricas de regressão
para comparar execuções e identificar degradação sem examinar logs manualmente.

**Why this priority**: A visualização transforma os resultados técnicos em evidência operacional
para decidir se o modelo continua adequado.

**Independent Test**: Pode ser testado concluindo duas execuções identificadas e verificando se o
painel permite consultar e comparar MAE, MSE, RMSE e R² de ambas.

**Acceptance Scenarios**:

1. **Given** uma execução de treinamento concluída, **When** o responsável abre o painel, **Then** as
   métricas MAE, MSE, RMSE e R² aparecem associadas à versão do modelo e ao horário da execução.
2. **Given** duas ou mais execuções, **When** um período é selecionado, **Then** o responsável consegue
   comparar a evolução de cada métrica no período.
3. **Given** uma execução falha ou rejeitada, **When** o painel é consultado, **Then** seu estado fica
   visível sem ser confundido com uma versão aprovada.

### Edge Cases

- O dataset é obtido, mas contém valores ausentes, infinitos, duplicados ou colunas divergentes.
- Há dados insuficientes para preservar conjuntos independentes de treino e teste.
- Uma métrica resulta em valor indefinido ou não finito.
- O treinamento é interrompido depois de gerar apenas parte dos artefatos.
- Não existe modelo aprovado quando o ambiente local conteinerizado é iniciado.
- O serviço de previsão recebe valores extremos, atributos adicionais ou tipos inválidos.
- O destino das métricas está temporariamente indisponível durante ou após o treinamento.
- O serviço Grafana externo está indisponível enquanto o armazenamento local de métricas continua
  recebendo resultados.
- Duas execuções semanais se sobrepõem ou tentam promover modelos simultaneamente.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema MUST utilizar como fonte inicial o California Housing referenciado pelo
  código atual do repositório e MUST incluir um snapshot versionado desse dataset na imagem de
  treinamento, identificado por versão e checksum.
- **FR-002**: O sistema MUST validar presença, esquema, tipos, valores ausentes, valores não finitos,
  duplicidades e exatamente 20.640 registros no snapshot California Housing desta versão antes do
  treinamento.
- **FR-003**: O sistema MUST separar dados de treino e teste de forma determinística e MUST impedir
  que registros do conjunto de teste influenciem o ajuste do modelo.
- **FR-004**: O sistema MUST registrar para cada execução a versão do código, referência dos dados,
  parâmetros, horários, estado final, artefato de modelo e métricas de avaliação.
- **FR-005**: O sistema MUST calcular MAE, MSE, RMSE e R² no conjunto de teste com as observações reais
  e as previsões na ordem matematicamente correta.
- **FR-006**: O sistema MUST considerar elegível somente um candidato com métricas finitas e R² de
  pelo menos 0,50. Quando houver campeão anterior, o aumento relativo de MAE e o aumento relativo de
  RMSE, calculados individualmente como `(novo - anterior) / anterior`, MUST ser menores ou iguais a
  5%. Se a métrica anterior for zero, somente um novo valor igual a zero satisfaz o gate. Na primeira
  promoção aplicam-se apenas os limites absolutos.
- **FR-007**: O sistema MUST preservar o último modelo aprovado quando uma execução falhar ou quando
  o candidato não satisfizer os critérios de promoção.
- **FR-008**: O ambiente local Docker MUST incluir treinamento, previsão e armazenamento persistente
  de métricas em unidades versionadas e reproduzíveis, sem incluir credenciais ou dados sensíveis
  nas imagens. A imagem de treinamento MUST incluir o snapshot de dados definido em FR-001 e MUST
  executar sem baixar dados durante o treinamento.
- **FR-009**: O ambiente local conteinerizado MUST informar o estado de saúde de cada componente, a
  versão do ambiente e a versão do modelo carregado.
- **FR-010**: O sistema MUST aceitar uma solicitação de previsão com os atributos documentados do
  dataset, validar a entrada e retornar o preço previsto e a versão do modelo usada.
- **FR-011**: O sistema MUST publicar MAE, MSE, RMSE, R², estado da execução e decisão de promoção com
  identificadores de execução, modelo e horário.
- **FR-012**: O serviço Grafana externo MUST conseguir consultar o armazenamento de métricas do
  ambiente local e exibir os valores atuais e o histórico de MAE, MSE, RMSE e R², permitindo seleção
  de período e distinção entre execuções aprovadas, rejeitadas e com falha.
- **FR-013**: O sistema MUST manter as métricas disponíveis mesmo quando a execução mais recente
  falhar e MUST sinalizar dados de painel desatualizados.
- **FR-014**: O treinamento completo MUST poder ser iniciado manualmente e por agenda semanal, sem
  promover o mesmo resultado mais de uma vez em execuções repetidas.
- **FR-015**: Uma falha de validação, treinamento, avaliação, publicação de métricas ou empacotamento
  MUST produzir diagnóstico rastreável e MUST impedir a promoção do candidato.
- **FR-016**: Cada versão do ambiente local conteinerizado MUST permitir verificar a correspondência
  entre fonte de dados, execução de treinamento, modelo aprovado e versão do ambiente.
- **FR-017**: Cada execução MUST treinar e avaliar regressão linear, Ridge, Lasso, árvore de decisão e
  floresta aleatória usando a mesma divisão de treino e teste; os parâmetros, artefatos e métricas de
  cada candidato MUST ser registrados separadamente.
- **FR-018**: Entre os candidatos elegíveis, o sistema MUST selecionar o menor RMSE; em caso de
  empate, MUST selecionar o menor MAE e, persistindo o empate, o maior R². Se o empate permanecer,
  MUST selecionar deterministicamente pela ordem das famílias listadas em FR-017.
- **FR-019**: O sistema MUST publicar saúde do serviço de inferência, quantidade de solicitações,
  quantidade de erros e distribuição de latência por janela temporal, identificando a versão do
  ambiente e do modelo. Logs de inferência, reload, saúde e promoção MUST incluir, quando
  disponíveis, `training_run_id`, `model_version` e `environment_version`.
- **FR-020**: O Grafana MUST disponibilizar alertas para ausência de execução semanal bem-sucedida
  por mais de oito dias, indisponibilidade da inferência e violação dos limites de qualidade do
  modelo.

### Scope Boundaries

- Esta feature inclui validação dos dados existentes, treinamento, avaliação, promoção do modelo,
  previsão conteinerizada e visualização das métricas de regressão.
- Esta feature não inclui aquisição de novas fontes de dados, enriquecimento por APIs externas,
  interface gráfica para solicitar previsões nem implantação em nuvem. A implantação na Azure for
  Students será especificada e aceita em uma feature futura independente.
- Monitoramento de drift de produção, alertas de drift e alertas baseados em enriquecimento externo
  ficam fora deste primeiro incremento; os três alertas operacionais de FR-020 permanecem no escopo
  e o histórico necessário para alertas futuros MUST ser preservado.

### Key Entities *(include if feature involves data)*

- **Dataset de imóveis**: Snapshot versionado de atributos de imóveis e preço-alvo incluído na imagem
  de treinamento; possui referência de origem, versão, checksum, esquema, quantidade de registros e
  resultado de validação.
- **Execução de treinamento**: Evento rastreável com código, dados, parâmetros, horários, estado,
  métricas e decisão de promoção.
- **Modelo candidato**: Um dos artefatos de regressão linear, Ridge, Lasso, árvore de decisão ou
  floresta aleatória resultantes de uma execução, associado à sua família, parâmetros, métricas e
  critérios de elegibilidade.
- **Modelo aprovado**: Candidato que satisfez todos os portões de qualidade e pode atender previsões.
  Quando mais de um candidato for elegível na mesma execução, é o vencedor determinado por RMSE,
  MAE, R² e ordem determinística das famílias, nessa sequência.
- **Registro de métricas**: Valores de MAE, MSE, RMSE e R² associados a uma execução, versão do modelo,
  instante de medição e estado de aprovação.
- **Ambiente local conteinerizado**: Conjunto versionado que reúne treinamento, previsão e
  armazenamento persistente de métricas e expõe a identidade e a saúde de seus componentes.
- **Solicitação de previsão**: Conjunto de atributos de um imóvel submetido para estimativa, com
  validação e vínculo à versão do modelo que respondeu.
- **Métrica de inferência**: Heartbeat e agregado temporal identificado por versões do ambiente e do
  modelo, contendo saúde, volume, erros e percentis de latência, sem payloads de imóveis.
- **Evidência semanal**: Manifesto imutável que vincula coleta/verificação do snapshot, validação,
  treinamento, decisão, saúde da entrega e rollback ao identificador do workflow.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% das execuções concluídas registram referência dos dados, parâmetros, artefato,
  MAE, MSE, RMSE, R², estado e decisão de promoção.
- **SC-002**: Em cinco repetições com os mesmos dados e parâmetros, 100% produzem a mesma decisão de
  promoção e métricas iguais dentro da tolerância numérica documentada.
- **SC-003**: 100% dos datasets inválidos usados nos testes são rejeitados antes do treinamento e não
  alteram o modelo aprovado.
- **SC-004**: Em host Linux de referência com 4 CPUs, 8 GiB de RAM, 10 GiB livres, Docker/Compose já
  instalados e imagens/dependências previamente baixadas, uma pessoa consegue iniciar o ambiente
  local conteinerizado e obter uma previsão válida em até 10 minutos, sem configurar dependências
  Python manualmente.
- **SC-005**: Pelo menos 95% das previsões válidas retornam um resultado em até 2 segundos durante um
  teste de 100 solicitações sequenciais no ambiente de referência definido em SC-004.
- **SC-006**: As métricas de uma execução concluída ficam consultáveis no painel em até 5 minutos e
  permanecem associadas à execução correta em 100% dos casos testados.
- **SC-007**: Um responsável consegue identificar em até 2 minutos o melhor e o pior resultado entre
  cinco execuções e explicar qual modelo está aprovado usando somente o painel.
- **SC-008**: Uma execução agendada completa coleta/restauração do snapshot imutável, validação,
  treinamento, avaliação e decisão em até 30 minutos no ambiente de referência definido em SC-004,
  ou registra claramente a etapa e a causa da falha.
- **SC-009**: Cinco execuções iniciadas sem acesso à internet concluem a leitura e validação do mesmo
  snapshot, comprovado por versão e checksum idênticos.
- **SC-010**: 100% das execuções concluídas registram resultados separados para os cinco tipos de
  modelo e aplicam a mesma divisão de treino e teste a todos eles.
- **SC-011**: Em cinco repetições com candidatos e métricas idênticos, 100% selecionam o mesmo modelo
  vencedor pela ordem RMSE, MAE, R² e família.
- **SC-012**: Após indisponibilidade, falha semanal ou violação de qualidade, o estado correspondente
  fica visível para o responsável no Grafana em até 5 minutos.

## Assumptions

- “Dataset do repositório” significa o California Housing carregado pelo código atual. Embora ainda
  não exista arquivo de dados local no estado presente do repositório, a entrega desta feature inclui
  um snapshot versionado diretamente na imagem de treinamento.
- O preço-alvo e os atributos permanecem com o significado e a unidade definidos pela fonte do
  California Housing.
- A primeira execução aprovada usa os limites absolutos definidos nesta especificação; comparações
  relativas passam a valer a partir do segundo candidato.
- A divisão de treino e teste usa uma semente fixa e mantém o teste isolado de seleção e ajuste.
- O usuário principal é a pessoa responsável por treinar, operar e avaliar o modelo; autenticação e
  múltiplos perfis de acesso não fazem parte deste incremento.
- Docker e Grafana são restrições obrigatórias fornecidas pelo usuário e pela constituição; a escolha
  dos demais componentes de implementação será feita na fase de planejamento.
- O Grafana é o único serviço externo ao ambiente local conteinerizado e recebe configuração para
  consultar no mesmo host o PostgreSQL publicado apenas em `127.0.0.1`. Acesso remoto exige túnel,
  TLS e firewall e permanece fora deste incremento.
- A execução local é o limite de entrega deste incremento; nenhuma validação de implantação em nuvem
  faz parte de seus critérios de aceite.
- O ambiente de referência possui recursos suficientes para executar o dataset atual e acesso à
  fonte já utilizada pelo projeto na primeira obtenção dos dados.
