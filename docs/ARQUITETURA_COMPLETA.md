# PedIA — Arquitetura completa do Escritório Virtual Multiagente (hackathon iFood)

> Documento de referência para o PDF final. Tudo aqui foi conferido no código da `main` em 18/10/2026
> (após o PR #20) ou em testes executados nesse dia. Onde algo não está pronto, está escrito que não está.

---

## 1. O que é o produto

Um **chatbot vendedor** que atende o consumidor por **texto ou áudio**. Por trás dele, um **escritório
virtual de agentes de IA** entende o pedido, pesquisa no iFood, monta e confere propostas e decide como
apresentá-las. São duas audiências, com duas telas:

- **Consumidor:** vê só o chat, as recomendações e os avisos relevantes à compra.
- **Gestor comercial:** vê o escritório: cada agente, as mensagens entre eles, as ferramentas usadas,
  os conflitos, as decisões com justificativa, as sugestões de desconto e os indicadores.

Tipos de pedido atendidos:

1. **Comida de restaurante**, com pessoas, orçamento, restrições alimentares, preferências e
   complementos ("pizza para 4 até R$ 120 com uma opção vegetariana"; "parmegiana com coca e batata frita").
2. **Compra de supermercado**, na hora ou **agendada** ("compra do mês no mercado: arroz 5 kg, 2 feijões,
   leite e café"; "mercado todo sábado às 10h: ...").

**Princípio de projeto: a IA entende e julga; o código calcula e garante.** Preço, total, orçamento,
restrição, abertura da loja e origem dos dados são conferidos por regras. Toda resposta de IA é validada
contra um esquema JSON; se a IA falhar, cada agente tem uma regra de reserva e o atendimento continua.

---

## 2. Componentes e como se conectam

```
 Navegador (http://localhost:8080)
   │
   ▼
 Proxy Node (frontend/scripts/proxy.mjs, porta 8080)
   ├── /api/*  ─────────────►  API FastAPI (backend/api, porta 8000)
   │                              ├── Agentes (backend/agents): orquestrador + 9 especialistas
   │                              ├── Memória (backend/memory): SQLite da sessão, memória do cliente, RAG
   │                              ├── Transcrição local Whisper (backend/integrations/local_transcription.py)
   │                              └── Runtime OpenCode (backend/integrations/agent_runtime.py)
   │                                        │ HTTP
   │                                        ▼
   │                                 OpenCode Server (porta 4096)
   │                                   ├── MCP iFood remoto: consumer-mcp.ifood.com.br/marketplace (OAuth)
   │                                   └── Modelo de IA (na apresentação: Anthropic claude-haiku-5-5)
   └── resto  ──────────────►  Expo Web / React Native Web (frontend, porta 8081)
```

| Peça | Tecnologia | Papel |
|---|---|---|
| Frontend | Expo 54, React Native 0.81 + React Native Web, TypeScript | Chat do comprador, escritório do gestor e Análise financeira |
| Proxy | Node + `http-proxy` | Mesma origem: `/api/*` vai para a 8000, o resto para a 8081 |
| API | Python, FastAPI, Uvicorn, Pydantic | Contrato HTTP/SSE v1, sessões, eventos, autorização de demo |
| Agentes | Python, só biblioteca padrão | Orquestração e especialistas, com IA por meio de uma porta |
| Memória | Python + SQLite | Estado por atendimento, histórico do cliente, RAG em Markdown |
| Runtime de IA e ferramentas | Cliente HTTP do OpenCode Server | Executa busca MCP e raciocínio estruturado |
| Busca | MCP do iFood, ferramenta `searchOffers` | Única fonte de produtos, preços e lojas |
| Áudio | faster-whisper (modelo `small`, CPU) + ffmpeg | Fala em português → texto revisável |

Os módulos se conhecem só por **portas** (interfaces em `backend/agents/ports.py`): `AgentRuntimePort`,
`MemoryPort`, `EventSink`, `KnowledgePort`, `CustomerMemoryPort`, `StrategyOutcomePort` e `SchedulePort`.
Os agentes não importam HTTP, OpenCode, MCP nem banco.

---

## 3. Uma mensagem, de ponta a ponta

1. **Áudio (opcional):** o chat grava pelo microfone ou recebe um arquivo e envia para
   `POST /api/v1/audio/transcriptions`.
   - A API aceita mpeg, mp4, ogg, wav e webm, com até 10 MiB.
   - O ffmpeg converte o áudio para 16 kHz mono, com limite de 120 s, e o Whisper transcreve em português.
   - O texto volta com `requires_confirmation: true`. **A transcrição não dispara agentes**: o cliente
     revisa o texto e envia.
   - O áudio não é gravado em disco.
2. **Envio:** `POST /api/v1/chat/messages` com `client_message_id`, que torna o envio idempotente: repetir a
   mesma mensagem não roda os agentes de novo. A resposta é `202 accepted`; o resultado chega por eventos.
3. **Despacho:** a API processa uma mensagem por vez por sessão (trava por sessão) e chama
   `orchestrator.handle_message(SessionContext)` numa thread.
4. **Agentes:** o Orquestrador lê a memória do atendimento, chama o Intérprete e escolhe, pelo registro,
   quais especialistas rodar. Cada passo emite eventos estruturados.
5. **Eventos:** cada evento é gravado no estado da API e só então transmitido por
   `GET /api/v1/sessions/{id}/events` (SSE).
   - O comprador recebe só os eventos `customer`/`both`; o gestor recebe `admin`/`both`.
   - O painel pode se reconstruir pelo histórico (`/history`) e pelo `snapshot`.
6. **Resposta:** o chat mostra o texto e os cards de recomendação. Nada é comprado: "fechado" registra o
   aceite (e o agendamento, quando houver), e o bot diz explicitamente que o envio ao iFood não é feito.

---

## 4. Frontend (`frontend/`)

- **Abas** (`App.tsx`):
  - **Chatbot** (`ChatScreen`);
  - **Dashboard**, **Painel de Agentes** e **Conflitos** (`OfficeScreen`, com o grafo de comunicação
    `AgentGraph`);
  - **Análise financeira** (`CeoScreen`).
- **Chat:**
  - texto, gravação de áudio (`useAudioRecorder`) e envio de arquivo (`expo-document-picker`), com o
    texto transcrito editável antes de enviar;
  - botão "Novo atendimento";
  - seletor de **clientes fictícios** (Ana, Bruno, Carla, Diego, ou sem histórico), enviado como
    `initial_context.name`.
- **Análise financeira** (`services/executive.ts`): indicadores calculados a partir dos eventos reais de
  cada atendimento (sem dado, o valor fica `null`) e **monitoria de estratégias**: quantas vezes cada
  estratégia foi oferecida e aceita.
- **Conexão** (`services/api.ts`):
  - usa `/api/v1` na mesma origem e SSE com `react-native-sse`;
  - o comprador envia `X-Demo-Role: customer` e o gestor `X-Demo-Role: admin`, inclusive no SSE;
  - `EXPO_PUBLIC_USE_MOCKS=true` liga os dados simulados (`src/mocks`); o padrão é a API real.
- **Agentes dinâmicos:** a interface não conhece nomes fixos de agentes. Nome, papel e estado vêm do
  catálogo (`GET /api/v1/agents`) e dos eventos, então um agente novo aparece sem mudança no frontend.
- Testes: `npx tsc --noEmit` (sem erros) e `npm test` (7 de 7).

---

## 5. API (`backend/api/`)

### Endpoints (prefixo `/api/v1`)

| Método e caminho | O que faz |
|---|---|
| `POST /sessions` | Cria o atendimento (`client_id` e `initial_context` opcional). Resposta 201 |
| `POST /audio/transcriptions` | Transcreve o áudio (multipart `audio` + `language=pt-BR`). Sem STT configurado: `STT_UNAVAILABLE` |
| `POST /chat/messages` | Envia a mensagem (texto ou áudio já revisado). Resposta 202, idempotente por `client_message_id` |
| `GET /sessions/{id}/events` | SSE com os eventos autorizados: `after_seq` ou `Last-Event-ID`, keep-alive a cada 15 s |
| `GET /sessions/{id}/history` | Histórico paginado (`after_seq`, `limit` até 200), filtrado por audiência |
| `GET /sessions/{id}/snapshot` | Estado completo: mensagens, recomendações, carrinho; agentes só para o gestor |
| `GET /agents` | Catálogo de agentes (somente gestor) |
| `GET /admin/overview` | Métricas agregadas, sem dados pessoais; o que não é medido vem `null` |
| `POST /orders/submit` | **Não habilitado**: responde `503 ORDER_SUBMISSION_UNAVAILABLE` (não há ferramenta de pedido) |

### Regras do contrato v1 (resumo do `PROMPT.md` §15)
- JSON em `snake_case`, datas em UTC ISO 8601, `schema_version: 1`.
- Dinheiro em **centavos inteiros**; valor desconhecido é `null`.
- As chaves de cada objeto são fechadas e os nulos ficam explícitos.
- Erro com formato único: `code`, `message`, `retryable`, `details`.
- Tipos de evento: `session_started`, `chat_message`, `agent_status`, `agent_message`, `tool_activity`,
  `knowledge_retrieved`, `memory_changed`, `pattern_identified`, `discount_proposed`,
  `conflict_detected`, `decision_made`, `recommendations_ready`, `cart_changed`,
  `order_status_changed`, `error` e `session_closed`.
  - `cart_changed` e `order_status_changed` existem no contrato, mas nenhum fluxo os emite hoje.

### Identidade e segurança (modo local de demonstração)
- `DemoIdentityResolver` usa identidades fictícias: comprador `client_demo_1` e gestor `manager_demo_1`,
  no tenant `tenant_demo`.
- No modo real, o papel de gestor só é aceito com `--local-demo-admin` e só para conexões locais
  (loopback). A primeira chamada de gestor emite um cookie `HttpOnly` opaco, para o `EventSource` manter
  o papel.
- O pedido do comprador com `X-Demo-Role: customer` nunca herda o papel de gestor.
- O comprador só acessa a própria sessão (403 em sessão de outro cliente) e não recebe eventos `admin`.
- **Isto é autenticação de demonstração, não de produção.**

### Estado e persistência
- Sessões, eventos, histórico e idempotência ficam em memória (`InMemoryBackendState`): **reiniciar a API
  apaga os atendimentos**.
- O estado compartilhado dos agentes por atendimento fica em SQLite, por padrão em
  `backend/api/.local/session-memory.sqlite3`.
- `APP_MEMORY_BACKEND=ephemeral` usa memória temporária no lugar do SQLite.

### Relógio das compras agendadas
- `ScheduleTicker` sobe com a API e chama `OrchestratorDispatcher.run_due_schedules()` a cada
  `APP_SCHEDULE_TICK_SECONDS` (padrão 30; `0` desliga).
- Cada compra vencida roda na sessão de origem, com a identidade do cliente e a mesma trava por sessão
  das mensagens.

---

## 6. Integrações (`backend/integrations/`)

### Runtime OpenCode (`OpenCodeAgentRuntime`) — dois tipos de chamada

1. **Busca** (`allowed_tools=("offer_search",)`): abre uma sessão no OpenCode com o agente `ifood-search`
   (`opencode.json`: só `ifood_searchOffers` liberado, até 3 passos). O modelo chama `searchOffers` com:
   - `resultKind=ITEM`, `pageSize=20`, ordenação por relevância e a localização;
   - `refinements.onlyOpen=true` (lojas abertas);
   - `refinements.itemRestrictions` quando há filtro alimentar;
   - `merchantType` vindo do contexto dos agentes: `RESTAURANT` por padrão ou `GROCERIES` para mercado;
   - `refinements.merchantId` quando os agentes pedem busca **dentro de uma loja**. Só é aceito UUID.

   Depois da chamada, o runtime **confere o que o modelo realmente pediu**: tipo de resultado,
   localização, filtros, vertical e loja. Se divergir, rejeita a resposta. As ofertas são montadas a
   partir do **resultado bruto do MCP**, nunca do texto do modelo. Só há `provider="ifood_mcp"` com
   chamada concluída comprovada; resposta MCP com erro no corpo conta como falha.
2. **Raciocínio** (`allowed_tools=()`): sessão com o agente `ifood-reasoning`, em que só a ferramenta
   interna `StructuredOutput` é liberada (MCP negado). A resposta é lida de `info.structured` e validada
   pelo esquema do agente.

Outros comportamentos do runtime:
- **Cota:** ao detectar retry por cota, aborta a chamada e suspende novas chamadas por 30 s.
- **Localização:** sem coordenadas do cliente, usa a referência pública de teste de São Carlos/SP
  (`run_local --real`). Isso fica registrado no resumo da busca e **não é o endereço do cliente**.
- **Lojas fechadas:** `--include-closed-restaurants` envia `onlyOpen=false` só para ensaio fora do horário.
  A opção sai marcada como "somente para teste" e a API bloqueia o envio dela como pedido.
- **Modelo:** o padrão do código é `google/gemini-3.8-flash`. A apresentação roda com
  `OPENCODE_PROVIDER_ID=anthropic` e `OPENCODE_MODEL_ID=claude-haiku-5-5`.

### Transcrição (`local_transcription.py`)
- Ativada com `APP_STT_PROVIDER=whisper` (`APP_STT_MODEL=small`).
- Processa um áudio por vez; com outro em andamento responde `STT_BUSY`.
- Sem fala detectada: `STT_NO_SPEECH`.
- Sem STT configurado, o chat por texto continua funcionando.

---

## 7. Agentes (`backend/agents/`)

**10 agentes no catálogo.** O orquestrador escolhe a esteira pelo registro (`registry.py`): cada agente diz
quando deve ser ativado (`should_activate`) e em que ordem roda (`order`). A seleção é reavaliada a cada
etapa. Conversa simples ("oi", "obrigado") não aciona a pesquisa.

```
Comida:   Intérprete → Pesquisador → Curador → Planejador → Auditor → Estrategista → Descontos → resposta
Mercado:  Intérprete → Pesquisador → Montador da cesta → Auditor → Descontos → agendamento → resposta
```

| Agente | IA? | Responsabilidade | Guarda-corpo no código |
|---|---|---|---|
| **Orquestrador** | Sim (texto final) | Coordena a esteira, resolve conflitos, registra decisões, reescreve a resposta ao cliente, cuida do agendamento e da confirmação | A resposta da IA só vale se citar a loja e o total exatos, sem outros valores e com todos os avisos; o texto da cesta de mercado é montado pelo código |
| **Intérprete** | Sim | Entende prato ou lista de mercado, complementos (até 3), pessoas, orçamento, restrições (de todos, de parte do grupo ou de um item), preferências, data e recorrência, e se é pedido, ajuste, confirmação ou conversa | "R$ X", "N pessoas" e "supermercado" escritos valem mais que a IA; só o cliente retira restrição; regras de reserva (`intent.py`, `chat.py`, `grocery.py`) |
| **Memória do cliente** | Não | Responde aos outros agentes com o histórico autorizado, o cadastro (restrições e preferências) e o desempenho das estratégias | Sem histórico, informa isso; nunca inventa |
| **Pesquisador** | Não (usa a ferramenta MCP) | Busca o prato e os complementos; procura o complemento que falta **dentro** dos restaurantes do prato; no mercado, busca item a item e completa a lista **dentro** do mercado que mais cobriu | Origem `ifood_mcp` só com prova; em sessão real, resultado sem prova é descartado |
| **Curador** (comida) | Sim | Julga se cada item é o pedido, quantas pessoas serve, quais restrições atende ou contraria e se um combo já traz o complemento; se nada serve, pede nova busca ao Pesquisador | Só julga itens da busca (até 30, priorizando os restaurantes que têm prato e complementos) |
| **Planejador** (comida) | Não | Combina itens por restaurante para o grupo, dentro do orçamento, com restrições e complementos; calcula subtotal, taxas e total em centavos | Complemento tem que ser o item sozinho (não "Estrogonofe + Coca"); lojas fechadas são descartadas |
| **Montador da cesta** (mercado) | Sim | Por mercado, escolhe o produto de cada item e a quantidade pelo tamanho pedido; indica restrições contrariadas | No máximo 6 candidatos por item para a IA; produto não julgado é avaliado por palavras, com aviso; uma loja por cesta |
| **Auditor** | Não | Confere cada proposta: item da busca, preço igual, mesma loja, loja aberta, quantidade, total, orçamento, restrições com prova ou aviso, nenhum desconto aplicado; na cesta, também se cada produto é de um item da lista | Proposta reprovada volta ao autor com o motivo |
| **Estrategista de vendas** (comida) | Sim | Consulta a Memória sobre quais estratégias convertem; escolhe a estratégia (`favorito`, `custo_beneficio`, `premium`, `novidade` ou `saudavel`), a ordem e o argumento; diz ao Especialista em descontos se o cliente precisa de incentivo | Só reordena opções aprovadas, sem números no argumento; **opção completa sempre vem antes da incompleta** |
| **Especialista em descontos** | Sim | Consulta a política no RAG e decide se sugere desconto e de quanto | Nunca acima do teto; lucro esperado calculado pelo código; sugestão só para o gestor, pendente de aprovação, fora do preço e da fala ao cliente |

### Como o raciocínio com IA funciona (`ai.py`)
- Todo agente com IA chama `ask()`: uma chamada **sem ferramentas** pelo mesmo `AgentRuntimePort`, com
  esquema JSON, timeout de 40 s e validação local.
- Cada consulta aparece no escritório como `tool_activity` `raciocinio_ia`, marcada como bem-sucedida ou
  com o motivo da falha.
- Se a IA falhar (cota, timeout, indisponível ou fora do formato), o agente usa a regra de reserva.

### Conflitos reais registrados (`conflict_detected` aberto → resolvido)
- **Curador × Pesquisador:** nada serve; o Curador pede nova busca, uma vez, e fica a melhor das duas.
- **Planejador (ou Montador) × Auditor:** proposta reprovada e descartada.
- **Orçamento × pedido:** não cabe; fica aberto até o cliente responder.
- **Estrategista × Descontos:** divergência sobre incentivo, resolvida pelo orquestrador.
- **Pedido × cadastro:** dieta por escolha (vegetariano, vegano) cede ao pedido explícito; restrição de
  saúde nunca cede.

### Comportamentos importantes
- **Restrições alimentares:**
  - vegetariano, vegano e sem glúten viram filtro da busca no iFood;
  - "uma opção vegetariana" garante ao menos um item vegetariano, sem filtrar a busca toda;
  - restrição de saúde avaliada só pela IA sai com aviso para confirmar com o restaurante (ou no
    rótulo, no mercado);
  - sem prova nem avaliação, a proposta é reprovada ou pergunta-se ao cliente.
- **Retomada incremental (`resumption.py`):** se só mudou orçamento ou número de pessoas, reaproveita a
  busca dos últimos 5 minutos, sem nova chamada ao iFood. "Busca de novo" força nova pesquisa.
- **"Mais barato":** só aceita opção com total menor que a mostrada; se não houver, diz que a mostrada já
  é a mais barata.
- **Memória do cliente:** "quero o mesmo" repete o último pedido. Clientes fictícios com histórico
  influenciam a estratégia (`pattern_identified`).
- **Confirmação:** "fechado" ou "pode ser" após uma sugestão registra o aceite e a estratégia que vendeu.
  **Não envia pedido ao iFood.**
- **Mercado e agendamento** (`grocery.py`, `grocery_basket.py`, `scheduler.py`):
  - lista com quantidades e tamanhos; "adiciona X" e "tira Y"; itens no singular;
  - datas: amanhã, dia da semana, dia do mês, horário, toda semana, a cada 15 dias, todo mês;
  - o horário precisa ter de 30 min a 4 meses de antecedência;
  - o agendamento fica pendente até o "fechado";
  - na data, a cesta é refeita com os preços do dia, de preferência no mesmo mercado, e o cliente
    confirma de novo: **o bot nunca compra sozinho**;
  - recorrente avança para a próxima data, pulando as datas perdidas;
  - "meus agendamentos" lista e "cancelar agendamento [n]" cancela.
- **Falhas** (`failures.py`): erros do runtime viram mensagens honestas ao cliente e eventos `error`.
  Códigos: `IFOOD_AUTH_REQUIRED`, `LOCATION_REQUIRED`, `SEARCH_QUERY_INVALID`, `IFOOD_TOOL_UNAVAILABLE`,
  `IFOOD_UNAVAILABLE`, `LLM_QUOTA`, `LLM_TIMEOUT`, `LLM_INVALID_OUTPUT` e `AGENT_ERROR`. O detalhe técnico
  nunca vai para os eventos.

---

## 8. Memória e conhecimento (`backend/memory/`)

| Memória | Implementação | O que guarda | Duração |
|---|---|---|---|
| Do atendimento | `SQLiteMemory` (`MemoryPort`) | Restrições, orçamento, lista de compras, busca, candidatos, propostas, auditoria, última sugestão e conflitos abertos | Arquivo SQLite: sobrevive ao processo, mas a sessão HTTP correspondente não |
| Do cliente | `SQLiteCustomerMemory` (`CustomerMemoryPort` + `StrategyOutcomePort`) | Pedidos feitos ao bot (prato, quantidade, orçamento, data), cadastro e resultado das estratégias. Sem nome, contato nem endereço | Em memória por processo |
| Clientes fictícios | `demo_seed.py` | 4 personas com cadastro, histórico e estratégias, mais volume fictício para a monitoria (`APP_DEMO_CUSTOMERS=0` desliga) | Recriados a cada início |
| Conhecimento comercial (RAG) | `MarkdownKnowledgeBase` (`KnowledgePort`) | `politica_comercial_demo.md` e `estrategias_venda_demo.md`, divididos por seção; busca por palavras com peso por raridade (idf) e tópicos, sem banco vetorial | Arquivos versionados |
| Agendamentos | `InMemorySchedules` (`SchedulePort`) | Lista, mercado, data, recorrência e estado (pendente, ativo, concluído, cancelado) | Em memória por processo |

- **Concorrência:** `save_patch` exige a revisão esperada. Se outra gravação veio antes, levanta
  `RevisionConflict` e o orquestrador tenta de novo. A gravação é atômica e auditada por chave.
- **Política de desconto da demo** (bloco `params` do documento): desconto de 5%, pedido mínimo de R$ 80,
  teto de R$ 15, margem suposta de 30% e conversão de 50% sem desconto contra 65% com desconto.
  **Todos são hipóteses DEMO.**
- **RAG não substitui o iFood:** preço, disponibilidade e taxas vêm sempre da busca atual.

---

## 9. Modos de execução

- **`demo`** (padrão, sem rede):
  - catálogo fictício de 5 restaurantes e 3 mercados (`backend/agents/demo/catalog.py`);
  - IA simulada por regras (`demo/runtime.py`);
  - tudo marcado como `provider="demo"` e "[dados de demonstração]";
  - nunca apresentado como iFood real. Também há um CLI: `python3 -m backend.agents.demo`.
- **`real`:** OpenCode + MCP iFood + modelo de IA reais. Não há troca silenciosa de real para demo.

### Subir tudo (como está nesta máquina)
```
opencode serve --hostname 127.0.0.1 --port 4096
APP_STT_PROVIDER=whisper APP_STT_MODEL=small OPENCODE_BASE_URL=http://127.0.0.1:4096 \
OPENCODE_PROVIDER_ID=anthropic OPENCODE_MODEL_ID=claude-haiku-5-5 OPENCODE_MODEL_VARIANT= \
python -m backend.api.run_local --real --port 8000 --local-demo-admin --include-closed-restaurants
cd frontend && EXPO_PUBLIC_USE_MOCKS=false EXPO_PUBLIC_DEMO_ADMIN=true npx expo start --web --port 8081
cd frontend && npm run proxy        # abrir http://localhost:8080
```
- `OPENCODE_MODEL_VARIANT=` vazio é obrigatório para o Claude (o padrão `low` é do Gemini).
- Em horário comercial, tirar `--include-closed-restaurants`.
- As credenciais OAuth do iFood ficam em `backend/integrations/.local/`, ignorado pelo git.
- As chaves dos modelos ficam no OpenCode; nada disso vai para o repositório.

---

## 10. Testes e validação

- **Automatizados**, executados em 18/10/2026:
  - agentes: 176 ok;
  - memória: 19 ok;
  - API e integrações: 153 ok e 3 pulados (testes reais opt-in);
  - frontend: TypeScript sem erros e 7 de 7 testes.
- **Ao vivo**, com iFood real + Claude Haiku, pela API:
  - "lista do mercado: arroz 5kg, 2 feijoes, leite e café" e depois "adiciona detergente": cesta com
    5 de 5 itens num supermercado de São Carlos (R$ 60,41);
  - "parmegiana de frango com coca e batata frita": marmita parmegiana com fritas + Coca lata no mesmo
    restaurante (R$ 38,98);
  - "hambúrguer com coca e batata frita": lanche + Coca + Fritas; as 3 opções completas;
  - nos testes, os pedidos levaram de alguns segundos a cerca de 40 s, conforme o número de buscas.

---

## 11. Limites honestos

- **O MCP liberado só permite busca** (escopo `mcp.discovery.search.read`). Não existem ferramentas de
  carrinho, pedido, pagamento, agendamento ou desconto. Por isso:
  - "fechado" só registra o aceite;
  - `POST /orders/submit` responde que não está habilitado;
  - o agendamento é nosso e sempre pede confirmação.
- **Localização:** sem endereço do cliente, as buscas usam um ponto público de teste em São Carlos. Isso
  não confirma entrega no endereço de ninguém.
- **Taxa de serviço:** o iFood não informa na busca; o total sai sem ela, com aviso.
- **Persistência:** sessões HTTP, eventos, memória do cliente e agendamentos ficam em memória do
  processo. Só o estado dos agentes por atendimento fica em arquivo.
- **Autenticação:** é de demonstração (papéis fictícios), não de produção.
- **Dados comerciais:** margem, conversão e política de desconto são documentos e hipóteses DEMO.
- **Complementos:** se o restaurante não vende o complemento, o bot avisa "peça à parte". Ele não inventa.
- **Qualidade da IA:** os guarda-corpos limitam erros, mas o julgamento da IA (o que é o prato, o tamanho
  da embalagem) pode falhar. O Auditor confere o que é verificável por regra.
