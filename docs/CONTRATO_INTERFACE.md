# Contrato de Interface v1 — Escritório Virtual Multiagente

Este documento define o contrato completo entre o backend e o chatbot do comprador e o escritório da gestão comercial. Ele especifica somente transporte e dados; não define layout, componentes, navegação ou comportamento visual.

A fonte de verdade é a seção 15 de `PROMPT.md`. As listas de chaves são fechadas: objetos v1 não aceitam campos adicionais.

## 1. Regras gerais

- Prefixo HTTP: `/api/v1`.
- JSON em `snake_case`, codificado em UTF-8.
- `schema_version` é sempre o inteiro `1`.
- Datas são strings UTC ISO 8601, por exemplo `2026-10-17T18:00:00Z`.
- IDs são strings estáveis e opacas. O cliente não deve interpretar seu formato.
- `seq` é um inteiro crescente e único dentro de cada sessão, não global.
- `event_id` é globalmente único.
- Todas as chaves descritas neste documento são obrigatórias, mesmo quando seu valor puder ser `null`.
- Arrays vazios devem ser enviados como `[]`.
- Valores desconhecidos que aceitam nulabilidade devem ser enviados como `null`.
- Strings não podem ser vazias, salvo onde o contrato declarar isso explicitamente.
- Dinheiro é representado em centavos inteiros de BRL. Nunca usar `float`.
- `discount_bps` usa pontos-base: `1000` representa 10%.
- Uma resposta HTTP `202` com `status: "accepted"` significa apenas que a operação foi aceita para processamento assíncrono.
- O resultado assíncrono chega por SSE, histórico ou snapshot.
- Dados e integrações simuladas usam `mode: "demo"`.
- Resultados simulados não podem acionar pedidos reais.

Enums globais:

```text
Mode = "real" | "demo"

SessionStatus =
  "active" |
  "waiting_customer" |
  "closed" |
  "error"

AgentStatus =
  "idle" |
  "running" |
  "waiting" |
  "done" |
  "error"
```

## 2. Autenticação, autorização e privacidade

Para navegador, recomenda-se cookie de sessão `HttpOnly` e `Secure` em mesma origem, ou proxy same-origin. Os comandos HTTP devem usar proteção CSRF.

Tokens não podem aparecer em query strings, payloads SSE, respostas JSON ou logs.

`tenant_id` e `client_id` sempre são validados pelo backend. Um identificador enviado pelo navegador não constitui prova de autorização. O comprador acessa apenas sua sessão. O gestor acessa apenas empresas e atendimentos para os quais possui autorização.

Eventos com `visibility: "admin"` nunca são entregues ao comprador. Eventos com `visibility: "both"` devem conter somente dados adequados aos dois públicos.

## 3. Modelos compartilhados

### 3.1 `AgentDefinition`

Todas as chaves são obrigatórias e não nulas.

```json
{
  "agent_id": "researcher",
  "name": "Pesquisador",
  "role": "Busca de ofertas",
  "description": "Pesquisa produtos e restaurantes",
  "capabilities": ["offer_search"],
  "enabled": true
}
```

| Campo | Tipo | Nulo | Regra |
|---|---|---:|---|
| `agent_id` | `string` | não | Identificador opaco do agente |
| `name` | `string` | não | Nome exibível |
| `role` | `string` | não | Papel do agente |
| `description` | `string` | não | Descrição da responsabilidade |
| `capabilities` | `string[]` | não | Pode ser `[]` |
| `enabled` | `boolean` | não | Indica disponibilidade |

Novos agentes aparecem no catálogo sem criar novos campos ou enums no frontend.

### 3.2 `AgentRuntime`

Estado de um agente em uma sessão específica.

```json
{
  "agent_id": "researcher",
  "status": "running",
  "task_id": "task_1",
  "summary": "Pesquisando opções"
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `agent_id` | `string` | não |
| `status` | `AgentStatus` | não |
| `task_id` | `string` | sim |
| `summary` | `string` | sim |

### 3.3 `ChatMessage`

```json
{
  "message_id": "msg_001",
  "role": "customer",
  "input_mode": "audio",
  "text": "Quero jantar por até quarenta reais.",
  "created_at": "2026-10-17T18:00:00Z"
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `message_id` | `string` | não |
| `role` | `"customer" \| "assistant"` | não |
| `input_mode` | `"text" \| "audio"` | não |
| `text` | `string` | não |
| `created_at` | `string(date-time)` | não |

Respostas do assistente sempre usam `input_mode: "text"`, inclusive quando a mensagem original veio de áudio.

### 3.4 `CartItem`

```json
{
  "product_id": "prd_1",
  "name": "Hambúrguer",
  "quantity": 2,
  "unit_price_cents": 2990
}
```

| Campo | Tipo | Nulo | Restrição |
|---|---|---:|---|
| `product_id` | `string` | não | — |
| `name` | `string` | não | — |
| `quantity` | `integer` | não | `> 0` |
| `unit_price_cents` | `integer` | não | `>= 0` |

### 3.5 `Recommendation`

```json
{
  "recommendation_id": "rec_1",
  "merchant_id": "rest_1",
  "merchant_name": "Restaurante Exemplo",
  "items": [
    {
      "product_id": "prd_1",
      "name": "Hambúrguer",
      "quantity": 2,
      "unit_price_cents": 2990
    }
  ],
  "currency": "BRL",
  "subtotal_cents": 5980,
  "delivery_fee_cents": 500,
  "other_fees_cents": 0,
  "discount_cents": 0,
  "total_cents": 6480,
  "eta_minutes": 35,
  "reasons": ["Dentro do orçamento"],
  "warnings": [],
  "data_origin": "ifood_mcp"
}
```

| Campo | Tipo/enum | Nulo | Restrição |
|---|---|---:|---|
| `recommendation_id` | `string` | não | — |
| `merchant_id` | `string` | não | — |
| `merchant_name` | `string` | não | — |
| `items` | `CartItem[]` | não | Pode ser `[]` |
| `currency` | literal `"BRL"` | não | — |
| `subtotal_cents` | `integer` | sim | Quando informado, `>= 0` |
| `delivery_fee_cents` | `integer` | sim | Quando informado, `>= 0` |
| `other_fees_cents` | `integer` | sim | Quando informado, `>= 0` |
| `discount_cents` | `integer` | não | `>= 0` |
| `total_cents` | `integer` | sim | Quando informado, `>= 0` |
| `eta_minutes` | `integer` | sim | Quando informado, `>= 0` |
| `reasons` | `string[]` | não | Pode ser `[]` |
| `warnings` | `string[]` | não | Pode ser `[]` |
| `data_origin` | `"ifood_mcp" \| "demo"` | não | — |

`total_cents` somente é preenchido quando todos os valores necessários forem conhecidos:

```text
subtotal_cents + delivery_fee_cents + other_fees_cents - discount_cents
```

Somente descontos autorizados e aplicáveis entram em `discount_cents`. Um desconto apenas sugerido não altera o total.

### 3.6 `Cart`

```json
{
  "cart_id": "cart_1",
  "status": "draft",
  "items": [
    {
      "product_id": "prd_1",
      "name": "Hambúrguer",
      "quantity": 2,
      "unit_price_cents": 2990
    }
  ],
  "currency": "BRL",
  "total_cents": 6480,
  "data_origin": "ifood_mcp"
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `cart_id` | `string` | sim |
| `status` | `"empty" \| "draft" \| "ready" \| "submitted" \| "error"` | não |
| `items` | `CartItem[]` | não |
| `currency` | literal `"BRL"` | não |
| `total_cents` | `integer >= 0` | sim |
| `data_origin` | `"ifood_mcp" \| "demo"` | não |

### 3.7 `InitialContext`

Contexto mínimo que a interface pode fornecer ao criar uma sessão:

```json
{
  "name": "Ana",
  "age": null,
  "location": "São Paulo, SP",
  "preferences": ["comida japonesa"],
  "restrictions": ["vegetariana"]
}
```

| Campo | Tipo | Nulo | Regra |
|---|---|---:|---|
| `name` | `string` | sim | Não vazia quando informada |
| `age` | `integer` | sim | Quando informada, entre `0` e `130` |
| `location` | `string` | sim | Não vazia quando informada |
| `preferences` | `string[]` | não | Pode ser `[]`; itens não vazios |
| `restrictions` | `string[]` | não | Pode ser `[]`; itens não vazios |

Quando `initial_context` for um objeto, essas cinco chaves são obrigatórias. Os dados têm origem na interface e **não são considerados dados provenientes ou verificados pelo iFood**. Para o MVP, eles entram na memória operacional da sessão e ficam disponíveis ao orquestrador antes da primeira mensagem; não são gravados automaticamente na memória persistente.

## 4. Endpoints HTTP

### 4.1 Criar sessão

```http
POST /api/v1/sessions
Content-Type: application/json
```

Request com contexto inicial:

```json
{
  "client_id": "client_demo_1",
  "initial_context": {
    "name": "Ana",
    "age": null,
    "location": "São Paulo, SP",
    "preferences": ["comida japonesa"],
    "restrictions": ["vegetariana"]
  }
}
```

| Campo | Tipo | Obrigatório | Nulo |
|---|---|---:|---:|
| `client_id` | `string` | sim | sim |
| `initial_context` | `InitialContext` | não | sim |

`initial_context` é a única chave opcional deste request. Pode ser omitida ou enviada como `null`, preservando a criação de sessão já existente:

Para atendimento anônimo:

```json
{
  "client_id": null
}
```

O backend deve validar que `client_id` pertence ao comprador autenticado ou à conta de demonstração. O identificador enviado não constitui prova de identidade ou autorização. O tenant não é recebido no body; ele é resolvido pelo backend.

Dados de `initial_context` são fornecidos pela interface e não são considerados dados verificados pelo iFood. Informações da conta iFood são recuperadas separadamente pelo backend somente quando a integração e as permissões tiverem sido confirmadas.

Response `201`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_alias": "Cliente #1",
  "mode": "demo",
  "status": "active",
  "created_at": "2026-10-17T18:00:00Z"
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `session_id` | `string` | não |
| `client_alias` | `string` | não |
| `mode` | `Mode` | não |
| `status` | `SessionStatus` | não |
| `created_at` | `string(date-time)` | não |

### 4.2 Transcrever áudio

```http
POST /api/v1/audio/transcriptions
Content-Type: multipart/form-data
```

Campos multipart exatos:

| Campo | Tipo | Obrigatório | Regra |
|---|---|---:|---|
| `audio` | arquivo binário | sim | Áudio a transcrever |
| `language` | `string` | não | Valor `"pt-BR"`; padrão `"pt-BR"` |

Não enviar áudio ao MCP do iFood.

Response `200`:

```json
{
  "schema_version": 1,
  "transcription_id": "tr_1",
  "text": "Quero hambúrguer sem cebola.",
  "language": "pt-BR",
  "requires_confirmation": true
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `transcription_id` | `string` | não |
| `text` | `string` | não |
| `language` | `string` | não |
| `requires_confirmation` | `boolean` | não |

A resposta serve para revisão do usuário. A transcrição, isoladamente, não dispara agentes nem pedidos. STT indisponível usa o erro HTTP comum com `error.code: "STT_UNAVAILABLE"`. O chat por texto continua disponível.

### 4.3 Enviar mensagem ao chat

```http
POST /api/v1/chat/messages
Content-Type: application/json
```

Request:

```json
{
  "session_id": "sess_1",
  "client_message_id": "msg_client_1",
  "text": "Quero hambúrguer sem cebola.",
  "input_mode": "audio",
  "transcription_id": "tr_1"
}
```

| Campo | Tipo/enum | Nulo | Regra |
|---|---|---:|---|
| `session_id` | `string` | não | Não vazio |
| `client_message_id` | `string` | não | Não vazio |
| `text` | `string` | não | Não vazio |
| `input_mode` | `"text" \| "audio"` | não | — |
| `transcription_id` | `string` | sim | `null` para texto; string válida para áudio |

Exemplo para texto:

```json
{
  "session_id": "sess_1",
  "client_message_id": "msg_client_2",
  "text": "Quero comida para quatro pessoas.",
  "input_mode": "text",
  "transcription_id": null
}
```

`client_message_id` garante idempotência por sessão. Repetir a mesma solicitação não pode executar novamente os agentes.

Response `202`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_message_id": "msg_client_1",
  "status": "accepted"
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `session_id` | `string` | não |
| `client_message_id` | `string` | não |
| `status` | literal `"accepted"` | não |

A resposta final do assistente chega posteriormente como evento `chat_message`.

### 4.4 Obter catálogo de agentes

```http
GET /api/v1/agents
```

Response `200`:

```json
{
  "schema_version": 1,
  "agents": [
    {
      "agent_id": "researcher",
      "name": "Pesquisador",
      "role": "Busca de ofertas",
      "description": "Pesquisa produtos e restaurantes",
      "capabilities": ["offer_search"],
      "enabled": true
    }
  ]
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `agents` | `AgentDefinition[]` | não |

O catálogo não contém posição, layout ou configuração visual.

### 4.5 Obter snapshot da sessão

```http
GET /api/v1/sessions/{session_id}/snapshot
```

Response `200`:

```json
{
  "schema_version": 1,
  "session": {
    "session_id": "sess_1",
    "client_alias": "Cliente #1",
    "status": "active",
    "mode": "demo",
    "created_at": "2026-10-17T18:00:00Z",
    "updated_at": "2026-10-17T18:01:00Z"
  },
  "last_seq": 3,
  "agents": [
    {
      "agent_id": "researcher",
      "status": "running",
      "task_id": "task_1",
      "summary": "Pesquisando opções"
    }
  ],
  "messages": [
    {
      "message_id": "msg_client_1",
      "role": "customer",
      "input_mode": "audio",
      "text": "Quero hambúrguer sem cebola.",
      "created_at": "2026-10-17T18:00:30Z"
    }
  ],
  "recommendations": [],
  "cart": null
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `session` | objeto | não |
| `last_seq` | `integer >= 0` | não |
| `agents` | `AgentRuntime[]` | não |
| `messages` | `ChatMessage[]` | não |
| `recommendations` | `Recommendation[]` | não |
| `cart` | `Cart` | sim |

Objeto `session`:

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `session_id` | `string` | não |
| `client_alias` | `string` | não |
| `status` | `SessionStatus` | não |
| `mode` | `Mode` | não |
| `created_at` | `string(date-time)` | não |
| `updated_at` | `string(date-time)` | não |

O backend pode filtrar elementos privados dos arrays conforme a audiência, mas não pode remover chaves do objeto.

### 4.6 Obter histórico de eventos

```http
GET /api/v1/sessions/{session_id}/history?after_seq=3&limit=200
```

| Parâmetro | Tipo | Restrição |
|---|---|---|
| `session_id` | `string` | Path parameter |
| `after_seq` | `integer` | Exclusivo: retorna somente `seq > after_seq` |
| `limit` | `integer` | De `1` a `200` |

Response `200`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "events": [],
  "last_seq": 3,
  "has_more": false
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `session_id` | `string` | não |
| `events` | `OfficeEvent[]` | não |
| `last_seq` | `integer >= 0` | não |
| `has_more` | `boolean` | não |

Eventos são ordenados por `seq` crescente. Quando `events` estiver vazio, `last_seq` contém o valor de `after_seq`. Caso contrário, contém o último evento devolvido.

### 4.7 Obter visão geral administrativa

```http
GET /api/v1/admin/overview
```

Response `200`:

```json
{
  "schema_version": 1,
  "mode": "demo",
  "window": {
    "from": "2026-10-17T00:00:00Z",
    "to": "2026-10-18T00:00:00Z"
  },
  "metrics": {
    "sessions_started": 12,
    "messages_received": 31,
    "recommendations_made": 8,
    "orders_submitted": 3,
    "orders_confirmed": 1,
    "conversion_rate": null,
    "average_response_ms": 1200,
    "estimated_ai_cost_cents": null,
    "revenue_cents": null,
    "estimated_profit_cents": null
  },
  "recent_sessions": [
    {
      "session_id": "sess_1",
      "client_alias": "Cliente #1",
      "status": "active",
      "updated_at": "2026-10-17T18:01:00Z",
      "last_seq": 3
    }
  ]
}
```

Campos de nível superior:

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `mode` | `Mode` | não |
| `window` | objeto | não |
| `metrics` | objeto | não |
| `recent_sessions` | array de objetos | não |

Objeto `window`:

| Campo | Tipo | Nulo |
|---|---|---:|
| `from` | `string(date-time)` | não |
| `to` | `string(date-time)` | não |

Objeto `metrics` — exatamente estas dez chaves:

| Campo | Tipo | Nulo | Restrição |
|---|---|---:|---|
| `sessions_started` | `integer` | não | `>= 0` |
| `messages_received` | `integer` | não | `>= 0` |
| `recommendations_made` | `integer` | não | `>= 0` |
| `orders_submitted` | `integer` | não | `>= 0` |
| `orders_confirmed` | `integer` | não | `>= 0` |
| `conversion_rate` | `number` | sim | Quando informado, entre `0` e `1` |
| `average_response_ms` | `integer` | sim | Quando informado, `>= 0` |
| `estimated_ai_cost_cents` | `integer` | sim | Quando informado, `>= 0` |
| `revenue_cents` | `integer` | sim | Quando informado, `>= 0` |
| `estimated_profit_cents` | `integer` | sim | Pode ser negativo |

Cada item de `recent_sessions`:

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `session_id` | `string` | não |
| `client_alias` | `string` | não |
| `status` | `SessionStatus` | não |
| `updated_at` | `string(date-time)` | não |
| `last_seq` | `integer` | não |

Números indisponíveis devem ser `null`, nunca inventados. Dados fictícios devem usar `mode: "demo"`.

### 4.8 Submeter pedido

```http
POST /api/v1/orders/submit
Content-Type: application/json
```

Este endpoint não executa pagamento. Ele tenta enviar um pedido após confirmação explícita e autorização.

Request:

```json
{
  "session_id": "sess_1",
  "recommendation_id": "rec_1",
  "client_action_id": "action_1",
  "confirmed": true
}
```

| Campo | Tipo | Nulo | Regra |
|---|---|---:|---|
| `session_id` | `string` | não | Não vazio |
| `recommendation_id` | `string` | não | Não vazio |
| `client_action_id` | `string` | não | Não vazio; chave de idempotência |
| `confirmed` | literal `true` | não | Deve ser `true` |

O backend valida recomendação, totais, permissões, idempotência e dados oficiais de carrinho/checkout. Em `mode: "demo"`, a operação é apenas simulada.

Response `202`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_action_id": "action_1",
  "status": "accepted"
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `session_id` | `string` | não |
| `client_action_id` | `string` | não |
| `status` | literal `"accepted"` | não |

O pedido não é considerado enviado enquanto não houver um evento `order_status_changed`.

### 4.9 Assinar eventos SSE

```http
GET /api/v1/sessions/{session_id}/events?after_seq=0
Accept: text/event-stream
```

Resposta com `Content-Type: text/event-stream` e cache desativado.

```text
id: 4
event: office_event
data: {"schema_version":1,"event_id":"evt_4","seq":4,"occurred_at":"2026-10-17T18:02:00Z","tenant_id":"tenant_demo","session_id":"sess_1","type":"agent_message","actor":{"kind":"agent","id":"researcher"},"recipient":{"kind":"agent","id":"planner"},"visibility":"admin","mode":"demo","payload":{"message_id":"agent_msg_1","task_id":"task_1","channel":"proposal","summary":"Duas opções disponíveis dentro do orçamento."}}

```

Regras:

- `id` contém o mesmo valor de `seq`.
- `event` é sempre `office_event`.
- `data` contém exatamente um `OfficeEvent`.
- `after_seq` e `Last-Event-ID`, em reconexão, indicam a última sequência consumida.
- Somente eventos com `seq` maior são enviados, em ordem crescente.
- Heartbeats podem ser comentários SSE `: keepalive`, sem JSON adicional.
- Eventos são persistidos antes da transmissão.
- Eventos perdidos podem ser recuperados pelo endpoint `/history`.
- O backend filtra os eventos conforme a audiência autenticada.

## 5. Envelope `OfficeEvent`

Todas as chaves são obrigatórias, inclusive `recipient` quando seu valor for `null`.

```json
{
  "schema_version": 1,
  "event_id": "evt_4",
  "seq": 4,
  "occurred_at": "2026-10-17T18:02:00Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_message",
  "actor": {
    "kind": "agent",
    "id": "researcher"
  },
  "recipient": {
    "kind": "agent",
    "id": "planner"
  },
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "message_id": "agent_msg_1",
    "task_id": "task_1",
    "channel": "proposal",
    "summary": "Duas opções disponíveis dentro do orçamento."
  }
}
```

| Campo | Tipo/enum | Nulo | Regra |
|---|---|---:|---|
| `schema_version` | literal `1` | não | — |
| `event_id` | `string` | não | Globalmente único |
| `seq` | `integer` | não | `>= 1`, crescente e único na sessão |
| `occurred_at` | `string(date-time)` | não | UTC |
| `tenant_id` | `string` | não | Autorizado pelo backend |
| `session_id` | `string` | não | — |
| `type` | `EventType` | não | Define a forma de `payload` |
| `actor` | `Actor` | não | Origem |
| `recipient` | `Actor` | sim | Destino, quando existir |
| `visibility` | `"admin" \| "customer" \| "both"` | não | — |
| `mode` | `Mode` | não | — |
| `payload` | objeto discriminado | não | Fechado por `type` |

### 5.1 `Actor`

Contém somente duas chaves:

```json
{
  "kind": "agent",
  "id": "researcher"
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `kind` | `"system" \| "agent" \| "customer" \| "tool"` | não |
| `id` | `string` | não |

O contrato transmite ações e justificativas verificáveis, não raciocínio interno dos modelos.

## 6. Comunicação entre agentes

A comunicação operacional entre agentes usa `type: "agent_message"`.

- `actor.kind` deve ser `"agent"`; `actor.id` identifica o agente de origem.
- `recipient.kind` deve ser `"agent"`; `recipient.id` identifica o agente de destino.
- `payload.message_id` identifica a mensagem.
- `payload.task_id` liga a comunicação à tarefa.
- `payload.channel` classifica a mensagem como `"request"`, `"proposal"`, `"review"` ou `"resolution"`.
- `payload.summary` contém um resumo operacional.
- `seq` determina a ordem dentro da sessão.
- `event_id` identifica globalmente o evento.
- O estado de cada agente é publicado separadamente por `agent_status` e aparece como `AgentRuntime` no snapshot.
- O catálogo é dinâmico; a interface não deve depender de IDs fixos de agentes.

## 7. Tipos de evento e payloads

Cada objeto abaixo é o conteúdo exato de `payload` para seu `type`. Todas as chaves mostradas são obrigatórias. Não são permitidas chaves adicionais.

### 7.1 `session_started`

```json
{
  "client_alias": "Cliente #1"
}
```

`client_alias`: `string`, não nulo.

### 7.2 `chat_message`

```json
{
  "message": {
    "message_id": "msg_client_1",
    "role": "customer",
    "input_mode": "audio",
    "text": "Quero hambúrguer sem cebola.",
    "created_at": "2026-10-17T18:00:30Z"
  }
}
```

`message`: `ChatMessage`, não nulo. O ator deve ser coerente com `message.role`.

### 7.3 `agent_status`

```json
{
  "agent_id": "researcher",
  "status": "running",
  "task_id": "task_1",
  "summary": "Pesquisando opções"
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `agent_id` | `string` | não |
| `status` | `AgentStatus` | não |
| `task_id` | `string` | sim |
| `summary` | `string` | sim |

### 7.4 `agent_message`

```json
{
  "message_id": "agent_msg_1",
  "task_id": "task_1",
  "channel": "proposal",
  "summary": "Duas opções disponíveis dentro do orçamento."
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `message_id` | `string` | não |
| `task_id` | `string` | não |
| `channel` | `"request" \| "proposal" \| "review" \| "resolution"` | não |
| `summary` | `string` | não |

### 7.5 `tool_activity`

```json
{
  "call_id": "call_1",
  "tool_name": "search_offers",
  "provider": "demo",
  "status": "succeeded",
  "duration_ms": 180,
  "summary": "Ofertas de demonstração consultadas."
}
```

| Campo | Tipo/enum | Nulo | Restrição |
|---|---|---:|---|
| `call_id` | `string` | não | — |
| `tool_name` | `string` | não | — |
| `provider` | `"ifood_mcp" \| "internal" \| "demo"` | não | — |
| `status` | `"started" \| "succeeded" \| "failed"` | não | — |
| `duration_ms` | `integer` | sim | Quando informado, `>= 0` |
| `summary` | `string` | não | — |

### 7.6 `knowledge_retrieved`

```json
{
  "query_id": "query_1",
  "topics": ["discount_policy"],
  "sources": [
    {
      "document_id": "doc_1",
      "title": "Política comercial de demonstração"
    }
  ],
  "count": 1
}
```

| Campo | Tipo | Nulo | Restrição |
|---|---|---:|---|
| `query_id` | `string` | não | — |
| `topics` | `string[]` | não | Pode ser `[]` |
| `sources` | `{document_id:string,title:string}[]` | não | Pode ser `[]` |
| `count` | `integer` | não | `>= 0` |

Cada item de `sources` contém exatamente `document_id: string` e `title: string`, ambos não nulos.

### 7.7 `memory_changed`

```json
{
  "scope": "session",
  "keys": ["budget", "party_size"],
  "summary": "Orçamento e número de pessoas registrados."
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `scope` | `"session" \| "customer" \| "company"` | não |
| `keys` | `string[]` | não |
| `summary` | `string` | não |

### 7.8 `pattern_identified`

```json
{
  "pattern_id": "pattern_1",
  "description": "Preferência recorrente por opções vegetarianas.",
  "basis": "demo",
  "evidence_count": 3,
  "confidence": "medium"
}
```

| Campo | Tipo/enum | Nulo | Restrição |
|---|---|---:|---|
| `pattern_id` | `string` | não | — |
| `description` | `string` | não | — |
| `basis` | `"historical_orders" \| "stated_preference" \| "demo"` | não | — |
| `evidence_count` | `integer` | não | `>= 0` |
| `confidence` | `"low" \| "medium" \| "high"` | não | — |

### 7.9 `discount_proposed`

```json
{
  "proposal_id": "discount_1",
  "recommendation_id": "rec_1",
  "discount_type": "percent",
  "discount_bps": 500,
  "discount_cents": null,
  "estimated_profit_delta_cents": null,
  "status": "suggested",
  "requires_approval": true,
  "reason": "Sugestão ilustrativa sujeita à aprovação comercial."
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `proposal_id` | `string` | não |
| `recommendation_id` | `string` | não |
| `discount_type` | `"percent" \| "fixed"` | não |
| `discount_bps` | `integer >= 0` | sim |
| `discount_cents` | `integer >= 0` | sim |
| `estimated_profit_delta_cents` | `integer` | sim |
| `status` | `"suggested" \| "approved" \| "rejected"` | não |
| `requires_approval` | `boolean` | não |
| `reason` | `string` | não |

Uma proposta de desconto não significa que o desconto foi aplicado. Somente descontos autorizados e aplicáveis aparecem em `Recommendation.discount_cents` e no total.

### 7.10 `conflict_detected`

```json
{
  "conflict_id": "conflict_1",
  "agent_ids": ["planner", "discount_specialist"],
  "description": "A proposta de desconto não possui margem confirmada.",
  "status": "open"
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `conflict_id` | `string` | não |
| `agent_ids` | `string[]` | não |
| `description` | `string` | não |
| `status` | `"open" \| "resolved"` | não |

### 7.11 `decision_made`

```json
{
  "decision_id": "decision_1",
  "recommendation_id": "rec_1",
  "summary": "Recomendação aprovada sem aplicar o desconto sugerido.",
  "reasons": ["Dentro do orçamento", "Atende à opção vegetariana"],
  "limitations": ["Desconto depende de aprovação comercial"]
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `decision_id` | `string` | não |
| `recommendation_id` | `string` | sim |
| `summary` | `string` | não |
| `reasons` | `string[]` | não |
| `limitations` | `string[]` | não |

### 7.12 `recommendations_ready`

```json
{
  "recommendations": [
    {
      "recommendation_id": "rec_1",
      "merchant_id": "rest_1",
      "merchant_name": "Restaurante Exemplo",
      "items": [
        {
          "product_id": "prd_1",
          "name": "Combo família com opção vegetariana",
          "quantity": 1,
          "unit_price_cents": 11000
        }
      ],
      "currency": "BRL",
      "subtotal_cents": 11000,
      "delivery_fee_cents": 800,
      "other_fees_cents": 0,
      "discount_cents": 0,
      "total_cents": 11800,
      "eta_minutes": 40,
      "reasons": ["Atende quatro pessoas", "Dentro do orçamento"],
      "warnings": ["Desconto sugerido ainda não foi aprovado"],
      "data_origin": "demo"
    }
  ]
}
```

`recommendations`: `Recommendation[]`, não nulo; pode ser `[]`.

### 7.13 `cart_changed`

```json
{
  "cart": {
    "cart_id": "cart_1",
    "status": "ready",
    "items": [
      {
        "product_id": "prd_1",
        "name": "Combo família com opção vegetariana",
        "quantity": 1,
        "unit_price_cents": 11000
      }
    ],
    "currency": "BRL",
    "total_cents": 11800,
    "data_origin": "demo"
  }
}
```

`cart`: `Cart`, não nulo.

### 7.14 `order_status_changed`

```json
{
  "order_id": "order_demo_1",
  "status": "submitted",
  "summary": "Pedido de demonstração submetido."
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `order_id` | `string` | sim |
| `status` | `"not_submitted" \| "submitted" \| "payment_pending" \| "confirmed" \| "failed"` | não |
| `summary` | `string` | não |

### 7.15 `error`

```json
{
  "code": "TOOL_UNAVAILABLE",
  "message": "A consulta de ofertas não está disponível.",
  "retryable": true
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `code` | `string` | não |
| `message` | `string` | não |
| `retryable` | `boolean` | não |

### 7.16 `session_closed`

```json
{
  "outcome": "order_submitted",
  "summary": "Atendimento encerrado após submissão do pedido."
}
```

| Campo | Tipo/enum | Nulo |
|---|---|---:|
| `outcome` | `"order_submitted" \| "abandoned" \| "closed"` | não |
| `summary` | `string` | não |

## 8. Erros HTTP padronizados

Qualquer falha HTTP usa exatamente esta estrutura:

```json
{
  "schema_version": 1,
  "request_id": "req_1",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "O orçamento informado precisa ser corrigido.",
    "retryable": false,
    "details": []
  }
}
```

| Campo | Tipo | Nulo |
|---|---|---:|
| `schema_version` | literal `1` | não |
| `request_id` | `string` | não |
| `error` | objeto | não |

Objeto `error`:

| Campo | Tipo | Nulo |
|---|---|---:|
| `code` | `string` | não |
| `message` | `string` | não |
| `retryable` | `boolean` | não |
| `details` | `string[]` | não |

O mesmo formato atende, entre outros, os status HTTP `400`, `401`, `403`, `404`, `409`, `422`, `429` e `503`.

O contrato não define um enum fechado para `error.code`. Exemplos especificados são `VALIDATION_ERROR` e `STT_UNAVAILABLE`. A resposta nunca pode conter tokens, credenciais, stack traces ou dados privados.

## 9. Exemplo completo de atendimento

O exemplo usa dados de demonstração. Portanto, `mode` é `"demo"`, a recomendação usa `data_origin: "demo"` e nenhuma operação representa um pedido real.

### 9.1 Criar sessão

Request:

```json
{
  "client_id": "client_demo_1",
  "initial_context": {
    "name": "Ana",
    "age": null,
    "location": "São Paulo, SP",
    "preferences": ["comida japonesa"],
    "restrictions": ["vegetariana"]
  }
}
```

Response `201`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_alias": "Cliente #1",
  "mode": "demo",
  "status": "active",
  "created_at": "2026-10-17T18:00:00Z"
}
```

### 9.2 Assinar eventos

```http
GET /api/v1/sessions/sess_1/events?after_seq=0
Accept: text/event-stream
```

```text
id: 1
event: office_event
data: {"schema_version":1,"event_id":"evt_1","seq":1,"occurred_at":"2026-10-17T18:00:00Z","tenant_id":"tenant_demo","session_id":"sess_1","type":"session_started","actor":{"kind":"system","id":"orchestrator"},"recipient":null,"visibility":"both","mode":"demo","payload":{"client_alias":"Cliente #1"}}

```

### 9.3 Transcrever áudio

Request multipart:

```text
audio=<arquivo binário>
language=pt-BR
```

Response `200`:

```json
{
  "schema_version": 1,
  "transcription_id": "tr_1",
  "text": "Quero comida para quatro pessoas, até cento e vinte reais, com uma opção vegetariana.",
  "language": "pt-BR",
  "requires_confirmation": true
}
```

A interface apresenta o texto para revisão. Depois da confirmação, envia a mensagem ao chat.

### 9.4 Enviar a mensagem confirmada

Request:

```json
{
  "session_id": "sess_1",
  "client_message_id": "msg_client_1",
  "text": "Quero comida para quatro pessoas, até cento e vinte reais, com uma opção vegetariana.",
  "input_mode": "audio",
  "transcription_id": "tr_1"
}
```

Response `202`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_message_id": "msg_client_1",
  "status": "accepted"
}
```

### 9.5 Sequência de eventos do atendimento

Cada objeto é transmitido como `data` de um evento SSE com `id: <seq>` e `event: office_event`.

```json
{
  "schema_version": 1,
  "event_id": "evt_2",
  "seq": 2,
  "occurred_at": "2026-10-17T18:00:30Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "chat_message",
  "actor": {"kind": "customer", "id": "client_demo_1"},
  "recipient": {"kind": "system", "id": "orchestrator"},
  "visibility": "both",
  "mode": "demo",
  "payload": {
    "message": {
      "message_id": "msg_client_1",
      "role": "customer",
      "input_mode": "audio",
      "text": "Quero comida para quatro pessoas, até cento e vinte reais, com uma opção vegetariana.",
      "created_at": "2026-10-17T18:00:30Z"
    }
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_3",
  "seq": 3,
  "occurred_at": "2026-10-17T18:00:31Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "memory_changed",
  "actor": {"kind": "system", "id": "orchestrator"},
  "recipient": null,
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "scope": "session",
    "keys": ["budget", "party_size", "dietary_preference"],
    "summary": "Orçamento, quantidade de pessoas e opção vegetariana registrados."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_4",
  "seq": 4,
  "occurred_at": "2026-10-17T18:00:32Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_message",
  "actor": {"kind": "agent", "id": "orchestrator"},
  "recipient": {"kind": "agent", "id": "researcher"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "message_id": "agent_msg_1",
    "task_id": "task_1",
    "channel": "request",
    "summary": "Pesquisar opções para quatro pessoas até R$ 120 com alternativa vegetariana."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_5",
  "seq": 5,
  "occurred_at": "2026-10-17T18:00:33Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_status",
  "actor": {"kind": "agent", "id": "researcher"},
  "recipient": null,
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "agent_id": "researcher",
    "status": "running",
    "task_id": "task_1",
    "summary": "Pesquisando opções."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_6",
  "seq": 6,
  "occurred_at": "2026-10-17T18:00:34Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "tool_activity",
  "actor": {"kind": "tool", "id": "demo_catalog"},
  "recipient": {"kind": "agent", "id": "researcher"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "call_id": "call_1",
    "tool_name": "search_offers",
    "provider": "demo",
    "status": "started",
    "duration_ms": null,
    "summary": "Consulta de demonstração iniciada."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_7",
  "seq": 7,
  "occurred_at": "2026-10-17T18:00:35Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "tool_activity",
  "actor": {"kind": "tool", "id": "demo_catalog"},
  "recipient": {"kind": "agent", "id": "researcher"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "call_id": "call_1",
    "tool_name": "search_offers",
    "provider": "demo",
    "status": "succeeded",
    "duration_ms": 180,
    "summary": "Ofertas de demonstração consultadas."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_8",
  "seq": 8,
  "occurred_at": "2026-10-17T18:00:36Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_message",
  "actor": {"kind": "agent", "id": "researcher"},
  "recipient": {"kind": "agent", "id": "planner"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "message_id": "agent_msg_2",
    "task_id": "task_1",
    "channel": "proposal",
    "summary": "Foi encontrada uma opção de demonstração dentro do orçamento."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_9",
  "seq": 9,
  "occurred_at": "2026-10-17T18:00:37Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "pattern_identified",
  "actor": {"kind": "agent", "id": "planner"},
  "recipient": null,
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "pattern_id": "pattern_1",
    "description": "Preferência recorrente por opções vegetarianas.",
    "basis": "demo",
    "evidence_count": 3,
    "confidence": "medium"
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_10",
  "seq": 10,
  "occurred_at": "2026-10-17T18:00:38Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "knowledge_retrieved",
  "actor": {"kind": "agent", "id": "discount_specialist"},
  "recipient": null,
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "query_id": "query_1",
    "topics": ["discount_policy"],
    "sources": [{"document_id": "doc_1", "title": "Política comercial de demonstração"}],
    "count": 1
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_11",
  "seq": 11,
  "occurred_at": "2026-10-17T18:00:39Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "discount_proposed",
  "actor": {"kind": "agent", "id": "discount_specialist"},
  "recipient": {"kind": "agent", "id": "orchestrator"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "proposal_id": "discount_1",
    "recommendation_id": "rec_1",
    "discount_type": "percent",
    "discount_bps": 500,
    "discount_cents": null,
    "estimated_profit_delta_cents": null,
    "status": "suggested",
    "requires_approval": true,
    "reason": "Sugestão ilustrativa sujeita à aprovação comercial."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_12",
  "seq": 12,
  "occurred_at": "2026-10-17T18:00:40Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_message",
  "actor": {"kind": "agent", "id": "planner"},
  "recipient": {"kind": "agent", "id": "auditor"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "message_id": "agent_msg_3",
    "task_id": "task_1",
    "channel": "review",
    "summary": "Revisar orçamento, opção vegetariana e situação do desconto."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_13",
  "seq": 13,
  "occurred_at": "2026-10-17T18:00:41Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "decision_made",
  "actor": {"kind": "agent", "id": "orchestrator"},
  "recipient": null,
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "decision_id": "decision_1",
    "recommendation_id": "rec_1",
    "summary": "Recomendação aprovada sem aplicar o desconto sugerido.",
    "reasons": ["Dentro do orçamento", "Atende quatro pessoas", "Inclui opção vegetariana"],
    "limitations": ["Dados de demonstração", "Desconto depende de aprovação comercial"]
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_14",
  "seq": 14,
  "occurred_at": "2026-10-17T18:00:42Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "recommendations_ready",
  "actor": {"kind": "agent", "id": "orchestrator"},
  "recipient": null,
  "visibility": "both",
  "mode": "demo",
  "payload": {
    "recommendations": [
      {
        "recommendation_id": "rec_1",
        "merchant_id": "rest_1",
        "merchant_name": "Restaurante Exemplo",
        "items": [
          {
            "product_id": "prd_1",
            "name": "Combo família com opção vegetariana",
            "quantity": 1,
            "unit_price_cents": 11000
          }
        ],
        "currency": "BRL",
        "subtotal_cents": 11000,
        "delivery_fee_cents": 800,
        "other_fees_cents": 0,
        "discount_cents": 0,
        "total_cents": 11800,
        "eta_minutes": 40,
        "reasons": ["Atende quatro pessoas", "Dentro do orçamento", "Inclui opção vegetariana"],
        "warnings": ["Dados de demonstração", "Desconto sugerido ainda não foi aprovado"],
        "data_origin": "demo"
      }
    ]
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_15",
  "seq": 15,
  "occurred_at": "2026-10-17T18:00:43Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_status",
  "actor": {"kind": "agent", "id": "orchestrator"},
  "recipient": null,
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "agent_id": "orchestrator",
    "status": "done",
    "task_id": "task_1",
    "summary": "Recomendação enviada ao cliente."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_16",
  "seq": 16,
  "occurred_at": "2026-10-17T18:00:44Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "chat_message",
  "actor": {"kind": "agent", "id": "orchestrator"},
  "recipient": {"kind": "customer", "id": "client_demo_1"},
  "visibility": "both",
  "mode": "demo",
  "payload": {
    "message": {
      "message_id": "msg_assistant_1",
      "role": "assistant",
      "input_mode": "text",
      "text": "Encontrei uma opção de demonstração para quatro pessoas, com alternativa vegetariana, por R$ 118,00.",
      "created_at": "2026-10-17T18:00:44Z"
    }
  }
}
```

### 9.6 Cliente confirma a submissão

Request:

```json
{
  "session_id": "sess_1",
  "recommendation_id": "rec_1",
  "client_action_id": "action_1",
  "confirmed": true
}
```

Response `202`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_action_id": "action_1",
  "status": "accepted"
}
```

### 9.7 Eventos após a confirmação

```json
{
  "schema_version": 1,
  "event_id": "evt_17",
  "seq": 17,
  "occurred_at": "2026-10-17T18:01:00Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "cart_changed",
  "actor": {"kind": "system", "id": "orchestrator"},
  "recipient": null,
  "visibility": "both",
  "mode": "demo",
  "payload": {
    "cart": {
      "cart_id": "cart_1",
      "status": "ready",
      "items": [
        {
          "product_id": "prd_1",
          "name": "Combo família com opção vegetariana",
          "quantity": 1,
          "unit_price_cents": 11000
        }
      ],
      "currency": "BRL",
      "total_cents": 11800,
      "data_origin": "demo"
    }
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_18",
  "seq": 18,
  "occurred_at": "2026-10-17T18:01:01Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "order_status_changed",
  "actor": {"kind": "system", "id": "orchestrator"},
  "recipient": null,
  "visibility": "both",
  "mode": "demo",
  "payload": {
    "order_id": "order_demo_1",
    "status": "submitted",
    "summary": "Pedido de demonstração submetido; nenhuma compra real foi executada."
  }
}
```

```json
{
  "schema_version": 1,
  "event_id": "evt_19",
  "seq": 19,
  "occurred_at": "2026-10-17T18:01:02Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "session_closed",
  "actor": {"kind": "system", "id": "orchestrator"},
  "recipient": null,
  "visibility": "both",
  "mode": "demo",
  "payload": {
    "outcome": "order_submitted",
    "summary": "Atendimento encerrado após submissão simulada do pedido."
  }
}
```

## 10. Compatibilidade v1

- Rotas, chaves, tipos, enums e nulabilidade são fechados.
- Objetos não aceitam propriedades adicionais.
- Campos obrigatórios não podem ser omitidos.
- O frontend não precisa conhecer classes Python, modelos de IA ou implementação de memória.
- Alterações incompatíveis exigem `/api/v2`, `schema_version: 2` e alinhamento entre as equipes.
- Um novo agente é apresentado pelo catálogo e pelos eventos existentes; não exige novo campo específico no frontend.
- OpenAPI, JSON Schema e modelos Pydantic devem ser derivados deste contrato e rejeitar chaves extras.
- Os exemplos deste documento devem passar pelos mesmos validadores usados pelo backend.
