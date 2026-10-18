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

## IA nos agentes (`ai.py`) — raciocínio com guarda-corpo

Os agentes conversam e **raciocinam com IA** pelo mesmo `AgentRuntimePort`, numa chamada **sem
ferramentas** (`allowed_tools=()`, `max_tool_calls=0`) que pede JSON no `output_schema`. A resposta é
validada; se a IA falhar, estourar cota ou sair do esquema, o agente usa a regra de reserva (o bot nunca
trava). Cada consulta aparece no escritório como `tool_activity` `raciocinio_ia` (`internal`, ou `demo`).

| Agente | IA decide | Guarda-corpo no código |
|---|---|---|
| Intérprete (`interpreter.py`) | o que o cliente quer, com o contexto da conversa: prato a buscar (corrige erros de digitação), pessoas ("eu e 3 amigos" = 4), orçamento, restrições (inclusive de parte do grupo: "um amigo é vegano" → `vegan_option`), preferências ("um já montado"), se é pedido, ajuste, confirmação ou papo, e conflito com o cadastro | R$ e "N pessoas" escritos vencem a IA; orçamento da IA só se a mensagem falar de dinheiro; restrições só acumulam; busca de 1–4 palavras; sem IA, as regras de `intent.py`/`chat.py` |
| Curador (`curator`) | se cada item é o prato pedido, quantas pessoas serve, **quais restrições atende pelo nome** e, se nada serve, **pede ao Pesquisador outra busca** (uma vez; conflito Curador × Pesquisador) | só julga itens que vieram da busca; restrição avaliada pela IA exige aviso ao cliente; sem IA, filtro por palavras e restrição sem tag bloqueia |
| Memória do cliente (`customer_memory`) | — (responde fatos) | histórico, cadastro (restrições/preferências) e desempenho das estratégias, com origem |
| Estrategista | **estratégia de venda** (`favorito`, `custo_beneficio`, `premium`, `novidade`, `saudavel`), ordem e argumento, após **perguntar à Memória** quais estratégias convertem; diz ao Especialista em descontos se o cliente precisa de incentivo | só reordena opções aprovadas; argumento sem números |
| Descontos | se sugere desconto e quanto (também em atendimento real, com hipóteses DEMO), ouvindo o Estrategista; se discordam, conflito resolvido pelo orquestrador | nunca acima do máximo da política; lucro calculado no código; nunca aplicado |
| Orquestrador | texto final ao cliente | precisa citar restaurante e total exatos, sem outros valores, com os avisos |

Planejador e auditor continuam por regra (dinheiro, orçamento, restrições, loja aberta, origem).
Planejador ↔ Auditor também conversam (pedido de conferência e reprovações). Conflitos registrados:
Curador × Pesquisador (nova busca), Planejador × Auditor (proposta reprovada), Orçamento × pedido
(aberto até o cliente responder), Estrategista × Descontos e Pedido × cadastro (dieta por escolha cede ao
pedido explícito; saúde nunca cede). "Fechado/pode ser" após uma sugestão registra a venda da estratégia
(`StrategyOutcomePort`), base da monitoria na Análise financeira.

Clientes fictícios da apresentação: `backend/memory/demo_seed.py` (cadastro, pedidos anteriores e
resultado das estratégias), escolhidos no chat pelo nome no `initial_context` (`persona_key`).
O runtime real faz essa chamada sem ferramentas pelo agente `ifood-reasoning` do OpenCode (só `StructuredOutput`).

## Portas (`ports.py`) — quem implementa

| Porta | Quem | Resumo |
|---|---|---|
| `AgentRuntimePort.run(RuntimeCall) -> RuntimeOutcome` | integrations | OpenCode + Gemini + MCP |
| `EventSink.emit(...)` | integrations | atribui `event_id`/`seq`/`tenant_id`/`mode`/`occurred_at`, persiste e só então transmite |
| `MemoryPort.load / save_patch` | memory | estado por atendimento, com revisão (`RevisionConflict`) |
| `CustomerMemoryPort.record_request / profile / forget` | memory | histórico por cliente; `build_orchestrator` usa o padrão de `backend.memory` (passe `customers=None` para desligar) |
| `KnowledgePort.search(tenant_id, query, topics, k) -> list[KnowledgeHit]` | memory | RAG sobre documentos comerciais; `build_orchestrator` usa a base padrão de `backend.memory` (passe `knowledge=None` para desligar) |

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
Opcionais: `tags, delivery_fee_cents, other_fees_cents, eta_minutes, is_open` (`null` = desconhecido).
`is_open: false` exclui a oferta (restaurante fechado); o runtime deve mapear `merchant.isOpen` para ele.
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

## Relevância ao pedido (`relevance.py`)
O orquestrador extrai os termos do prato ("marmita parmegiana") da mensagem, ou da memória (`search.terms`)
em follow-ups como "agora são 3 pessoas". O pesquisador manda só esses termos para a busca; o planejador
usa apenas ofertas cujo item ou restaurante correspondam (item vale mais que restaurante) e avisa quando
não há o prato exato ("opção mais próxima"); sem nenhuma oferta aderente, pergunta ao cliente em vez de
sugerir outra coisa. O auditor rejeita item sem relação com o pedido ou de restaurante fechado.
Pedido genérico ("quero comida") não é filtrado.

## Retomada incremental (`resumption.py`)
Mensagens seguintes do mesmo atendimento reaproveitam a última pesquisa, **sem chamar o runtime**, quando a
assinatura não mudou: prato (`search.terms`), restrições alimentares, localização do `initial_context` e
modo. Mudar só quantidade de pessoas, orçamento ou pedir "mais barato" replaneja com as mesmas ofertas
(`candidates` na memória). Nova busca quando: prato, restrição, localização ou modo mudam; a pesquisa tem
mais de 5 min (`SEARCH_TTL_S`, igual às evidências da integração; não congela preço/disponibilidade); o cliente pede ("busca de novo",
"outras opções"); a anterior falhou ou veio vazia; ou a sessão é `real` e os dados guardados não são
`ifood_mcp`. Memória: `last_search` = `{signature, at, count}`, gravado só após pesquisa bem-sucedida.
O gestor vê `agent_message` "Pesquisa reaproveitada, sem nova busca".

## Memória do cliente (entre atendimentos)
Com `client_id` (sessões anônimas não são lembradas): ao fim de um pedido com prato e recomendação
aprovada, o orquestrador registra prato/quantidade/orçamento (`memory_changed`, `scope: "customer"`, só
na primeira vez por atendimento). Num atendimento novo, "oi" responde "Da última vez você pediu X. Quer
pedir o mesmo?"; "quero o mesmo"/"de novo"/"o de sempre" repete o último prato com a mesma quantidade e
orçamento. O estrategista prioriza o prato favorito (2+ atendimentos) com `pattern_identified`
`basis: "stated_preference"`; o histórico fictício DEMO só entra se não houver histórico real.

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
- **Especialista em descontos:** só em sessão `demo`. Busca a política no RAG (`knowledge_retrieved` com o
  documento real) e usa os parâmetros do bloco `params` dele; sem RAG, usa a política embutida e diz isso;
  com RAG mas sem política recuperada, não sugere. Se o lucro esperado sob essas hipóteses melhorar, emite `discount_proposed` com `status="suggested"` e
  `requires_approval=true`, visível só ao gestor. O desconto **não** entra no total nem na fala ao cliente.

## Compras de supermercado, agendadas ou não (`grocery.py`, `grocery_basket.py`, `scheduler.py`)
"Compra do mês no mercado: arroz 5kg, 2 feijões, leite e café" e "mercado todo sábado às 10h: ...".

1. **Intérprete (IA)** devolve `tipo: mercado`, a `lista` completa (item, quantidade, tamanho) e o
   `agendamento` (data/hora/recorrência resolvidas a partir de `AGORA`). Reserva por regras em `grocery.py`
   ("supermercado"/"mercado" escrito vence a IA; "adiciona café", "tira o leite"; "amanhã", "sábado", "dia 25",
   "toda semana", "a cada 15 dias", "todo mês"). Datas em UTC, lidas e mostradas no horário de Brasília.
   Restrição que só aparece no nome de um item ("leite sem lactose") vale só para esse item.
2. **Pesquisador**: uma busca por item com `context.merchant_type = "GROCERIES"`; depois procura os itens que
   faltam **dentro** do mercado que mais cobriu a lista (`context.merchant_id`, até 4 buscas).
3. **Montador da cesta (IA, `grocery_basket`)**: por mercado, escolhe o produto de cada item ("doce de leite" não
   é "leite"), a quantidade pelo tamanho pedido (5 kg com pacote de 1 kg = 5) e as restrições que o produto
   contraria. O código monta a cesta (um mercado por proposta = uma entrega), soma o total e respeita o
   orçamento; avisa os itens que faltam. Sem IA: correspondência por palavras, com aviso.
4. **Auditor** (`audit_basket`): produto veio da busca, preço igual, mesmo mercado, é de um item da lista, não
   repetido, aprovado pelo Montador, restrições com prova ou aviso, totais e orçamento.
5. **Agendamento** (`scheduler.plan_schedule`, regra do orquestrador, não é agente): horário com 30 min a 4
   meses de folga; a cesta sai com "Agendo para ...". Fica **pendente** até o cliente confirmar ("fechado");
   aí vira `active`.
6. Na data, `orch.due_schedules(now)` lista os vencidos e `orch.run_schedule(id)` refaz a cesta **com os preços
   do dia**, de preferência no mesmo mercado, e pergunta ao cliente no atendimento de origem. Recorrente avança
   para a próxima data (datas perdidas são puladas); único vira `done`. **Nunca compra sozinho**: o MCP liberado
   só busca e toda compra exige confirmação.

"Meus agendamentos" lista; "cancelar agendamento [n]" cancela. Guarda: `SchedulePort` (`ports.py`), padrão
`schedules.InMemorySchedules` (memória do processo: reiniciar a API apaga). Planejador, Curador e Estrategista
não rodam em compra de mercado. Recomendação e eventos seguem o contrato v1 sem campos novos.

**Depende de fora do módulo** (proposto, não feito): o runtime real precisa repassar `merchant_type`/`merchant_id`
do `context` ao `searchOffers` (hoje fixa `merchantType=RESTAURANT`), e a API precisa chamar `due_schedules` +
`run_schedule` periodicamente. Sem isso, o modo demo funciona inteiro e o real busca no vertical errado.

## Eventos emitidos
`agent_status`, `agent_message` (`request|proposal|review|resolution`), `tool_activity`
(emitido após a chamada), `conflict_detected`, `decision_made`, `recommendations_ready`,
`knowledge_retrieved`, `pattern_identified`, `discount_proposed`, `memory_changed`,
`chat_message` (assistente), `error` (códigos em `failures.py`: `IFOOD_AUTH_REQUIRED`, `LOCATION_REQUIRED`,
`SEARCH_QUERY_INVALID`, `IFOOD_TOOL_UNAVAILABLE`, `IFOOD_UNAVAILABLE`, `LLM_QUOTA`, `LLM_TIMEOUT`,
`LLM_INVALID_OUTPUT`, `AGENT_ERROR`). O `detail` do runtime só escolhe a mensagem ao cliente; nunca é
copiado para eventos. `catalog()` inclui o `orchestrator`, que também emite `agent_status`.
Payloads com chaves fechadas, validadas em `events.py` contra a seção 15.4 do PROMPT.md.
Eventos de agentes: `visibility="admin"`; resposta ao cliente e recomendações: `"both"`.

## Memória: chaves que o módulo escreve
`constraints` (`budget_cents, party_size, dietary, preferences`), `conversation` (`stage`),
`shown` (`recommendation_id`, `total_cents` da última recomendação mostrada), `search` (`terms`),
`last_search` (`signature`, `at`, `count`, `extra_of`, `grocery_of`), `candidates`, `grocery` (`items`, `schedule`),
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
Padrões de compra a partir de histórico real e controle de cota (este é do runtime).
