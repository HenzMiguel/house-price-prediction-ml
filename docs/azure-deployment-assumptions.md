# Premissas para Azure for Students

Esta feature não cria recursos Azure e, portanto, seu custo Azure é **US$ 0**.

Uma feature futura de implantação deve reutilizar exatamente as imagens aprovadas pelo CI e:

- consultar créditos, regiões, cotas de CPU/memória e disponibilidade de Azure Container Instances;
- definir um teto mensal menor ou igual ao crédito estudantil disponível;
- mapear `postgres-data`, `mlflow-artifacts` e `model-registry` para persistência durável equivalente;
- fornecer segredos por mecanismo Azure, nunca por imagem ou variável versionada;
- manter usuários não-root, portas documentadas, TLS, health checks e logs correlacionados;
- não depender de Docker socket, filesystem do host ou `localhost` entre contêineres;
- executar readiness, previsão e rollback para a última imagem/modelo saudável;
- registrar imagem imutável, configuração, origem/checksum dos dados e consumo observado.

O envelope local inicial é 4 CPUs, 8 GiB de RAM e 10 GiB de armazenamento para toda a stack. Ele é
um limite de benchmark, não uma seleção automática de SKU. CPU, memória, disco, tráfego e duração
devem ser medidos novamente antes da estimativa Azure. Nenhum serviço pago ilimitado está aprovado.

