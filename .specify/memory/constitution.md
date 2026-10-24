# House Price Prediction MLOps Constitution

## Core Principles

### I. Experimentos Rastreáveis e Reprodutíveis

Todo treinamento e toda avaliação de modelo executados pela pipeline MUST registrar no MLflow a
versão do código, a referência imutável dos dados, os parâmetros, as métricas e os artefatos
produzidos. Um modelo somente pode ser promovido quando sua execução puder ser reproduzida a
partir desses registros e de dependências versionadas. Essa rastreabilidade permite auditar,
comparar e reverter decisões de modelagem.

### II. Dados Externos Confiáveis e Governados

Toda API externa MUST possuir contrato documentado, política de autenticação, limites de uso,
tratamento de timeout e retentativas e identificação da origem dos dados. Dados coletados MUST ser
validados quanto a esquema, completude, tipos, duplicidade e valores anômalos antes de alimentar
treinamento ou avaliação. Falhas de validação MUST impedir a promoção de modelos, preservar o último
artefato válido e produzir diagnóstico rastreável; dados brutos e transformados MUST ter versões ou
referências imutáveis para evitar treinamento silencioso com entradas desconhecidas.

### III. Automação Semanal Segura

A coleta, o tratamento, a avaliação e o treinamento MUST ser executáveis de ponta a ponta por um
workflow agendado do GitHub Actions ao menos uma vez por semana, além de permitir execução manual
controlada. O workflow MUST ser idempotente, ter etapas com estados e logs identificáveis e falhar
de forma explícita quando qualquer portão de dados, testes ou qualidade do modelo não for atendido.
Credenciais MUST ser obtidas de mecanismos de secrets e jamais armazenadas no repositório, nas
imagens ou nos logs.

### IV. Contêiner como Unidade de Entrega

Treinamento, serviço de inferência e componentes operacionais MUST ser empacotados em imagens Docker
reproduzíveis, com versões imutáveis, execução sem privilégios sempre que suportado e verificações de
saúde aplicáveis. Azure for Students permanece o ambiente final de implantação do projeto, mas uma
feature MAY encerrar na execução local quando seus limites de escopo adiarem explicitamente o deploy
para uma feature futura e seus critérios de aceite excluírem validação em nuvem. Nesse caso, a
feature local MUST produzir uma imagem imutável e documentar as premissas necessárias ao deploy
futuro. Quando uma feature incluir implantação, a mesma imagem aprovada pelos portões de CI MUST ser
implantada na Azure. A arquitetura MUST respeitar cotas e orçamento da assinatura estudantil,
documentar consumo esperado e manter um procedimento verificável de rollback para a última versão
saudável.

### V. Observabilidade Operacional e de Modelo

A solução MUST expor métricas consumíveis pelo Grafana para saúde do serviço, latência, erros,
volume de inferências e estado das execuções da pipeline. Métricas de qualidade do modelo e de dados,
incluindo degradação ou drift quando mensurável, MUST ser publicadas por versão do modelo e janela
temporal. Logs MUST ser estruturados e correlacionáveis com execução, versão do modelo e implantação,
sem dados sensíveis; alertas MUST existir para falha semanal, indisponibilidade e violação dos
limites de qualidade definidos na especificação.

## Restrições Técnicas e Operacionais

- MLflow é o sistema oficial de rastreamento de experimentos e artefatos de modelo.
- GitHub Actions é o orquestrador oficial de integração contínua e do ciclo semanal automatizado.
- Docker é o formato oficial de empacotamento, e Azure for Students é o ambiente-alvo de execução.
- Grafana é a interface oficial para painéis e alertas; a fonte de métricas MUST ser explicitamente
  definida na especificação da solução.
- Dependências, imagens, contratos de API, esquemas de dados e configurações de infraestrutura MUST
  ser versionados. Ambientes MUST ser configurados por variáveis e secrets externos ao código.
- Nenhum componente pode depender de recurso incompatível com as cotas ou os termos da assinatura
  Azure for Students. Escolhas com custo recorrente MUST incluir estimativa e limite de consumo.
- Dados pessoais ou sensíveis MUST ser minimizados, protegidos em trânsito e em repouso e excluídos
  de logs, métricas e artefatos, conforme a classificação documentada para cada fonte externa.

## Fluxo de Desenvolvimento e Portões de Qualidade

Toda mudança MUST passar por revisão e por CI antes da integração. O CI MUST executar testes
unitários dos tratamentos e da lógica da pipeline, testes de contrato das APIs externas, validação
dos dados, testes de integração dos componentes MLOps e verificação de construção da imagem Docker.
Falhas em qualquer portão MUST bloquear merge ou promoção.

Uma especificação de treinamento MUST definir, antes da execução, a divisão de dados, as métricas,
o baseline, os limites mínimos de aceitação e os critérios de promoção. Um novo modelo somente pode
substituir o vigente quando superar ou satisfazer esses critérios sem regressão crítica; caso
contrário, a execução MUST ser registrada no MLflow e o modelo vigente MUST permanecer ativo. Cada
implantação MUST registrar imagem, modelo, configuração e origem dos dados, e MUST ter validação de
saúde e caminho de rollback testado.

Mudanças em fontes externas, esquema de dados, contrato de inferência, critérios de promoção ou
infraestrutura MUST incluir documentação de impacto e testes correspondentes. A execução semanal
MUST gerar evidência consultável de coleta, validação, avaliação, decisão de promoção e resultado da
implantação, mesmo quando não houver novo modelo aprovado.

## Governance

Esta constituição prevalece sobre práticas conflitantes do projeto. Toda especificação, plano,
tarefa e pull request MUST demonstrar conformidade com os princípios e portões aplicáveis. Exceções
temporárias exigem justificativa, risco, responsável, prazo de expiração e plano de correção
documentados; conveniência ou pressão de prazo não constituem justificativa suficiente.

Emendas MUST ser propostas por pull request com motivação, impacto, plano de migração para artefatos
afetados e aprovação do mantenedor do projeto. A versão da constituição segue SemVer: MAJOR para
remoção ou redefinição incompatível de princípios, MINOR para novo princípio ou expansão material de
governança e PATCH para esclarecimentos sem mudança de obrigação. A data de última emenda MUST ser
atualizada em toda alteração aprovada.

Revisões de conformidade MUST ocorrer em cada pull request e antes de cada promoção para produção.
Ao menos uma vez por ciclo semanal, a evidência da pipeline, os alertas e a recuperabilidade do
último modelo válido MUST ser verificáveis. O consumo da Azure MUST ser verificável enquanto houver
uma implantação ativa nesse ambiente. O Sync Impact Report no topo deste arquivo é material
temporário de revisão e MUST ser removido antes do commit da emenda.

**Version**: 2.0.0 | **Ratified**: 2026-10-24 | **Last Amended**: 2026-10-24
