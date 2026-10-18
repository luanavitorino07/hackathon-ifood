# backend/agents — guia de integração

Cérebro do chatbot: recebe a mensagem do cliente, conversa ou aciona os agentes
(pesquisador → planejador → auditor) e devolve a resposta, as recomendações e os eventos.
**Não contém** OpenCode, Gemini, MCP, banco, HTTP nem tela: tudo isso entra por portas.

Só biblioteca padrão. Testes: `python3 -m unittest discover -s backend/agents/tests -t .`

## Uso (quem chama é a API)

```python
from backend.agents.bootstrap import build_orchestrator
from backend.agents.models import SessionContext

orch = build_orchestrator(runtime, memory, sink)   # as três portas, abaixo
out = orch.handle_message(SessionContext(
    session_id="sess_1", tenant_id="tenant_demo", client_id=None, mode="demo",
    message_text="Quero pizza para 2 pessoas até R$ 80", input_mode="text",
    initial_context=None))                         # dict do contrato v1, ou None
out.session_status   # "active" | "waiting_customer" | "error"
out.reply_text       # fala do chatbot (também sai como evento chat_message)
out.recommendations  # list[dict] no formato Recommendation do contrato v1
orch.catalog()       # list[dict] AgentDefinition, para GET /agents
```

- Chamada **síncrona**. Em API assíncrona, rode numa thread.
- Uma chamada por mensagem. Serialize chamadas da mesma sessão.
- Do `initial_context` só são lidos `location`, `preferences` e `restrictions`.

## Portas (`ports.py`) — quem implementa

| Porta | Quem | Resumo |
|---|---|---|
| `AgentRuntimePort.run(RuntimeCall) -> RuntimeOutcome` | integrations | OpenCode + Gemini + MCP |
| `EventSink.emit(...)` | integrations | atribui `event_id`/`seq`/`tenant_id`/`mode`/`occurred_at`, persiste e só então transmite |
| `MemoryPort.load / save_patch` | memory | estado por atendimento, com revisão (`RevisionConflict`) |

### `RuntimeCall` (entrada)
`agent_id, task_id, session_id, system, prompt, output_schema, allowed_tools=("offer_search",)`,
`max_tool_calls=3`, `timeout_s=60.0`, `context` (dict mínimo: `location` e/ou `dietary_filters`
com `VEGETARIAN|VEGAN|GLUTEN_FREE`).

### `RuntimeOutcome` (saída)
`ok, structured, tool_calls: tuple[ToolTrace], error, retry_after_s, detail`.
- `ok=True` ⇒ `error=None` e `structured` válido contra `output_schema`.
- `error`: `quota` | `timeout` | `invalid_output` | `unavailable`. Nunca deixar exceção vazar.
- `detail`: curto e sanitizado, só diagnóstico. Não vai para eventos.

### `ToolTrace`
`call_id, tool_name` (nome **lógico**, ex.: `offer_search`), `provider` (`ifood_mcp|internal|demo`),
`status` (`succeeded|failed`), `duration_ms`, `summary` (sem parâmetros, payload ou PII —
vai para o painel do gestor).

### `structured["offers"]` (esquema em `researcher.OFFER_SCHEMA`)
Obrigatórios: `product_id, name, unit_price_cents` (inteiro, centavos), `merchant_id, merchant_name`.
Opcionais: `tags, delivery_fee_cents, other_fees_cents, eta_minutes` (`null` = desconhecido).
Monte a partir dos **resultados reais do MCP**, nunca do texto do modelo.

## Regras que o código assume
- `data_origin="ifood_mcp"` só se houver `ToolTrace` `ifood_mcp` + `succeeded`. Sessão `real`
  sem essa prova é descartada. Resposta com `errors` no corpo conta como `failed`, mesmo com HTTP 200.
- Taxa de serviço ausente (`other_fees_cents=null`) entra como 0 e a recomendação traz aviso.
  Taxa de entrega desconhecida mantém `total_cents=null`.
- **Restrições alimentares:** vegetariana, vegana e sem glúten viram filtro de busca
  (`context.dietary_filters`); "uma opção vegetariana" não filtra a busca inteira, o planejador garante ao
  menos um item vegetariano. Sem tag comprobatória nas ofertas, a recomendação sai com o aviso
  "não comprovada pelo iFood". Qualquer outra restrição bloqueia e pergunta ao cliente.
- Orçamento, pessoas e restrições persistem entre mensagens (`MemoryPort`, chave `constraints`).
  Precedência, da menor para a maior: `initial_context` (só enquanto `constraints` ainda não existe
  na memória) < `constraints` persistidas < `session.constraints` < declaração explícita na mensagem.
  Depois da primeira mensagem o `initial_context` não é reaplicado, para não desfazer correções do cliente.

## Conversa (`chat.py`)
Classificação por regras, sem LLM. Só mensagens de **pedido** (comida, orçamento, pessoas) rodam
a esteira e chamam o runtime. Saudação, agradecimento, despedida, pedido vago, dúvida e texto
não entendido recebem resposta direta, sempre perguntando o que o cliente quer, e deixam a
sessão em `waiting_customer`. Pedido de "mais barato" só aceita opções com total menor que o da última recomendação mostrada
(`shown`); se não houver, o bot diz que aquela já é a mais barata em vez de repetir. Com pedido em andamento (`conversation.stage = "ordering"` na
memória), follow-ups também contam como pedido.

## Estratégia e desconto (dados DEMO, `commercial.py`)
- **Estrategista de vendas:** só reordena propostas já aprovadas pelo auditor, por preferência declarada
  (`initial_context.preferences`) e, em sessão `demo`, pelo histórico fictício de `client_demo_1`.
  Emite `pattern_identified` (`stated_preference` ou `demo`) e conta ao cliente o motivo.
- **Especialista em descontos:** só em sessão `demo`. Consulta a política DEMO (`knowledge_retrieved`) e,
  se o lucro esperado sob as hipóteses DEMO melhorar, emite `discount_proposed` com `status="suggested"` e
  `requires_approval=true`, visível só ao gestor. O desconto **não** entra no total nem na fala ao cliente.

## Eventos emitidos
`agent_status`, `agent_message` (`request|proposal|review|resolution`), `tool_activity`
(emitido após a chamada), `conflict_detected`, `decision_made`, `recommendations_ready`,
`knowledge_retrieved`, `pattern_identified`, `discount_proposed`,
`chat_message` (assistente), `error` (códigos em `failures.py`: `IFOOD_AUTH_REQUIRED`, `LOCATION_REQUIRED`,
`SEARCH_QUERY_INVALID`, `IFOOD_TOOL_UNAVAILABLE`, `IFOOD_UNAVAILABLE`, `LLM_QUOTA`, `LLM_TIMEOUT`,
`LLM_INVALID_OUTPUT`, `AGENT_ERROR`). O `detail` do runtime só escolhe a mensagem ao cliente; nunca é
copiado para eventos. `catalog()` inclui o `orchestrator`, que também emite `agent_status`.
Payloads com chaves fechadas, validadas em `events.py` contra a seção 15.4 do PROMPT.md.
Eventos de agentes: `visibility="admin"`; resposta ao cliente e recomendações: `"both"`.

## Memória: chaves que o módulo escreve
`constraints` (`budget_cents, party_size, dietary, preferences`), `conversation` (`stage`),
`shown` (`recommendation_id`, `total_cents` da última recomendação mostrada), `candidates`,
`data_origin`, `proposals`, `audit` (`approved`, `issues`). O módulo de memória
pode guardá-las como JSON opaco.

## Modo demonstração offline (plano B)
Roda **sem API, MCP, Gemini ou internet**, com catálogo FICTÍCIO (`demo/catalog.py`) e runtime simulado
(`demo/runtime.py`, `provider="demo"`):

```bash
python3 -m backend.agents.demo                 # conversa interativa no terminal
python3 -m backend.agents.demo --roteiro       # conversa pronta, para apresentar
python3 -m backend.agents.demo --escritorio    # mostra a comunicação entre os agentes (visão do gestor)
python3 -m backend.agents.demo --sem-tags      # imita o iFood real: sem tags de dieta nem taxa de serviço
python3 -m backend.agents.demo --falha quota   # demonstra o tratamento de falha
python3 -m backend.agents.demo --preferencia pizza --restricao vegetariana
```

`DemoCatalogRuntime` também implementa `AgentRuntimePort` e pode ser usado pela API no lugar do runtime real.

## Só para teste
`testing/fakes.py` (`FakeRuntime`, `InMemoryMemory`, `RecordingSink`) é **simulado**: seus
dados saem com `provider="demo"`/`data_origin="demo"` e nunca são promovidos a `ifood_mcp`.

## Fora do escopo atual
RAG real, padrões de compra a partir de histórico real e controle de cota (este é do runtime).
