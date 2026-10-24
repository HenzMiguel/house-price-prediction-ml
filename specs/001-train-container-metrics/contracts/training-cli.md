# Training CLI Contract

## Comando

O job é iniciado pelo Compose:

```bash
docker compose run --rm trainer train
```

O entrypoint também aceita:

```text
train
  --run-id UUID                 # opcional; gerado quando ausente
  --seed INTEGER                # padrão 42
  --test-fraction DECIMAL       # padrão 0.33
  --cv-folds INTEGER            # padrão 5
  --timeout-seconds INTEGER     # limite global compatível com 30 minutos
  --trial-budget FAMILY=COUNT   # repetível; Linear permanece 1
  --resume                      # retoma estudos da mesma run
```

Parâmetros de conexão, credenciais, caminhos de volumes e URIs são recebidos apenas por variáveis de
ambiente ou secrets; não são aceitos como argumentos para evitar exposição em histórico/process list.

## Saída padrão

Logs são JSON Lines, um evento por linha, com:

- `timestamp` UTC;
- `level`;
- `event`;
- `training_run_id`;
- `mlflow_run_id`, quando já disponível;
- `stage`;
- `candidate_family` e `trial_number`, quando aplicável;
- mensagem sem dados sensíveis.

A última linha em sucesso contém `event=training_completed`, `status`, `promoted`,
`model_version` (quando houver), métricas do vencedor e duração.

## Códigos de saída

| Código | Significado | Promoção |
|---|---|---|
| `0` | execução concluída, com ou sem candidato elegível | somente se elegível |
| `2` | configuração ou argumentos inválidos | não |
| `3` | dataset/manifesto inválido | não |
| `4` | dependência indisponível (PostgreSQL ou MLflow) | não |
| `5` | falha de otimização/avaliação | não |
| `6` | falha ao publicar observabilidade/artefatos | não |
| `7` | falha de promoção ou validação do pacote | não |
| `8` | execução concorrente detectada (`skipped_concurrent`) | não |
| `130` | interrupção solicitada | não |

Falhas atualizam a run pai e `observability.training_runs` quando esses destinos estiverem
disponíveis. Nenhum código diferente de zero pode alterar `current.json`.

## Idempotência e retomada

- O mesmo `--run-id` reutiliza nomes de estudo e chaves de UPSERT.
- Sem `--resume`, uma run já finalizada é recusada.
- Com `--resume`, somente trials faltantes e etapas não publicadas são retomados.
- Uma execução com promoção já confirmada retorna o resultado existente sem republicar o campeão.
- Apenas uma execução possui o advisory lock; concorrentes encerram com código 8.

## Evidências obrigatórias

Em conclusão, o job deve ter produzido ou atualizado:

1. run pai e runs filhas/trials no MLflow;
2. cinco finalistas com MAE, MSE, RMSE e R²;
3. gráficos de regressão e otimização;
4. projeções `observability` idempotentes;
5. decisão de promoção e, quando aprovada, pacote/manifesto no volume;
6. status final correlacionável em logs, MLflow e PostgreSQL.
