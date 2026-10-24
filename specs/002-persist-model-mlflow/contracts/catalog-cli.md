# Model Catalog CLI Contract

## Invocação

```bash
docker compose run --rm --entrypoint model-catalog trainer COMMAND [OPTIONS]
```

Conexões, credenciais e paths vêm somente de variáveis/secrets.

## Comandos

### `verify`

```text
model-catalog verify [--model-version VERSION] [--json]
```

Somente leitura. Valida volumes, manifestos, ledger, runs, artifacts, versões, alias e ponteiro. Sem
versão, verifica todas. Uma sonda de upload/download temporária pode ser habilitada por
`--probe-artifacts`; ela não cria ModelVersion e remove o artifact de diagnóstico ao concluir.

### `reconcile`

```text
model-catalog reconcile [--mode check|apply] [--trigger manual|startup|weekly|restore]
                        [--model-version VERSION] [--json]
```

Padrão `check`. `apply` obtém o lock, valida sem desserializar, reutiliza vínculo por identidade,
recupera somente pacote v2 autossuficiente, grava ledger/eventos e nunca promove pacote descoberto.

### `list`

```text
model-catalog list [--integrity STATUS] [--lifecycle STATUS] [--json]
```

Lista identidade, estados, checksums abreviados e IDs ativos sem carregar modelo.

### `resolve-champion`

```text
model-catalog resolve-champion --prefer volume --apply --confirm VERSION [--json]
```

Única resolução automática suportada: reparar alias/ledger para o pacote íntegro já apontado por
`current.json`. Não existe `--prefer mlflow`; alterar o serving exige promoção/rollback normal.

### `delete` e `purge`

```text
model-catalog delete --model-version VERSION [--apply --confirm VERSION] [--json]
model-catalog purge --deletion-id UUID --apply --confirm UUID [--json]
```

Delete é dry-run por padrão. Aplicação cria tombstone e move para trash; recusa campeão, último
modelo íntegro ou operação concorrente. Purge é separado e irreversível.

## Saída JSON Lines

Cada linha contém `event`, `operation_id`, `timestamp` e, quando aplicável, `model_version`, estados,
ação, resultado, reason code e IDs MLflow. A última é `catalog_operation_completed`, com status,
modo, trigger, contagens e `retryable`. Não inclui credenciais, URL de banco nem path absoluto host.

## Códigos de saída

| Código | Significado |
|---|---|
| `0` | concluído sem conflito |
| `2` | argumentos/configuração inválidos |
| `3` | concluído com item inválido/quarentenado |
| `4` | dependência indisponível; retryable |
| `5` | inconsistência volume/ledger/MLflow |
| `6` | falha ao persistir publicação/ledger |
| `7` | remoção/resolução protegida recusada |
| `8` | advisory lock indisponível |
| `130` | interrupção; operação retomável |

## Idempotência

- A mesma identidade mantém uma entrada, uma run ativa e uma versão ativa.
- Falha após upload é retomada por tags e intenção no ledger.
- `check`/`verify` não alteram estado, exceto a sonda temporária explicitamente solicitada.
- Repetir delete/purge concluído retorna o resultado persistido sem novo efeito.

