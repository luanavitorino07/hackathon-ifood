# Projeto iFood — visão geral, integrações e plano do Lorenzo

Atualizado em: 17 de outubro de 2026  
Branch responsável: `feat/integrations`  
Escopo do Lorenzo: `backend/integrations/**` e `backend/api/**`

## 1. Resumo em linguagem simples

O projeto é um chatbot de compras com um escritório multiagente nos bastidores.
O cliente pede comida por texto ou áudio. Os agentes entendem o pedido,
pesquisam ofertas, montam uma recomendação e registram eventos para o painel do
gestor.

O fluxo planejado é:

```text
Frontend do cliente
       |
       | HTTP JSON
       v
FastAPI do projeto
       |
       v
Orquestrador e agentes
       |
       | AgentRuntimePort
       v
OpenCode Server -----> Gemini 2.5 Flash
       |
       | chamada de tool MCP
       v
MCP oficial do iFood -----> sistemas do iFood

Agentes ---> EventSink ---> estado/histórico ---> SSE ---> painel do gestor
```

São três conexões diferentes:

1. **API HTTP do nosso projeto:** é a API FastAPI consumida pelo frontend.
2. **API HTTP do OpenCode Server:** permite que o backend controle o OpenCode
   programaticamente.
3. **MCP oficial do iFood:** fornece ferramentas como `searchOffers`; o OpenCode
   chama essas ferramentas usando OAuth do iFood.

O backend não criou uma API paralela para o iFood. A integração oficial ocorre
por meio do servidor MCP configurado no OpenCode.

## 2. Responsabilidade de cada componente

### Frontend

Responsabilidade da equipe de interface. Envia mensagens, consulta snapshots e
histórico e assina os eventos SSE. O backend não deve alterar telas, CSS ou
design.

### API FastAPI

Responsabilidade do Lorenzo em `backend/api/**`.

Ela oferece:

- criação de sessões;
- entrada de mensagens de texto ou texto já transcrito;
- endpoint preparado para áudio;
- catálogo de agentes;
- snapshot e histórico da sessão;
- eventos em tempo real por SSE;
- visão agregada do gestor;
- endpoint preparado para envio de pedido.

### Agentes e orquestrador

Responsabilidade da branch `feat/agents`, atualmente em
`origin/feat/agents@ac7fcf1`.

O orquestrador recebe um `SessionContext`, escolhe os agentes necessários e usa
três portas externas:

- `AgentRuntimePort`: OpenCode, Gemini e ferramentas MCP;
- `MemoryPort`: estado compartilhado da sessão;
- `EventSink`: persistência e transmissão dos eventos.

Saudações e agradecimentos são respondidos por regras e não gastam cota do
Gemini. O runtime é chamado somente quando a mensagem representa um pedido.

### OpenCode

O OpenCode é o runtime controlado pelo backend. Ele roda como servidor HTTP
local, normalmente em `http://127.0.0.1:4096`.

O backend usa o OpenCode para:

- criar uma sessão de execução;
- enviar o papel e o prompt do agente;
- habilitar somente a ferramenta MCP autorizada;
- executar o Gemini 2.5 Flash;
- receber a chamada e o resultado bruto da ferramenta.

O OpenCode pode ser controlado programaticamente pelo comando `opencode serve`.
A documentação oficial do servidor está em
<https://docs.opencode.ai/docs/server/>.

### Gemini

O Gemini 2.5 Flash interpreta o pedido e monta a chamada para `searchOffers`.
Ele não é a fonte dos preços. Produtos, preços, restaurantes, entrega e tempo
estimado precisam vir da resposta da ferramenta MCP.

A chave do Gemini deve ser configurada localmente no OpenCode usando
`/connect`, selecionando o provedor Google. Ela não deve ser colocada no Git,
no frontend ou em mensagens de chat. Consulte
<https://docs.opencode.ai/docs/providers/>.

O plano gratuito possui limites. O backend já normaliza erros de cota, timeout,
saída inválida e indisponibilidade, mas os limites precisam ser medidos no teste
real.

### MCP oficial do iFood

O MCP é a ponte padronizada entre o OpenCode e as ferramentas do iFood. O
servidor configurado atualmente é:

```text
https://consumer-mcp.ifood.com.br/marketplace
```

O escopo atual do MVP é:

```text
mcp.discovery.search.read
```

Na documentação do Offer Discovery existem seis ferramentas:

- `searchOffers`: pesquisa por texto;
- `browseOffers`: navegação do catálogo;
- `getRecommendations`: listas pré-curadas;
- `listItemTaxonomy`: categorias;
- `getMerchant`: detalhes do parceiro;
- `getItem`: detalhes do item.

O MVP implementa somente `searchOffers`. Não estão autorizadas ainda operações
de carrinho, pagamento ou envio de pedido real. Documentação oficial:
<https://mcp-developer.ifood.com.br/pt-BR/docs/guides/mcps/discovery/tools>.

### Memória

Enquanto a implementação persistente não estiver integrada, o bootstrap usa
`InMemoryMemory`, declarado pela branch dos agentes como memória de
demonstração. Ela é perdida ao reiniciar o processo.

`build_application(memory=...)` já permite trocar essa implementação por uma
`MemoryPort` real sem mudar os agentes nem o contrato HTTP.

## 3. Fluxo completo de uma mensagem

1. O frontend cria uma sessão em `POST /api/v1/sessions`.
2. O frontend envia a mensagem em `POST /api/v1/chat/messages`.
3. A API persiste a mensagem do cliente e devolve `202 accepted`.
4. O dispatcher executa o orquestrador síncrono em uma thread.
5. Chamadas da mesma sessão são serializadas para evitar concorrência.
6. O pesquisador cria um `RuntimeCall` com `allowed_tools=("offer_search",)`.
7. `OpenCodeAgentRuntime` descobre o identificador real de `searchOffers`.
8. Todas as outras ferramentas do OpenCode são desabilitadas para a chamada.
9. O Gemini cria uma chamada `searchOffers` com `resultKind="ITEM"`.
10. O OpenCode chama o MCP oficial do iFood via OAuth.
11. O runtime lê o resultado bruto da tool, não o texto inventado pelo modelo.
12. As ofertas são convertidas para o contrato interno dos agentes.
13. Os agentes planejam e auditam a recomendação.
14. Cada evento é persistido antes de ficar disponível no SSE.
15. O frontend recebe a resposta do assistente e as recomendações por SSE,
    snapshot ou histórico.

## 4. Contratos principais

### Mensagem enviada pelo frontend

```json
{
  "session_id": "sess_1",
  "client_message_id": "msg_front_1",
  "text": "Quero uma pizza até 60 reais",
  "input_mode": "text",
  "transcription_id": null
}
```

### Oferta entregue pelo runtime aos agentes

```json
{
  "product_id": "item_1",
  "name": "Pizza Margherita",
  "unit_price_cents": 2990,
  "merchant_id": "merchant_1",
  "merchant_name": "Pizzaria Exemplo",
  "tags": [],
  "delivery_fee_cents": 500,
  "other_fees_cents": null,
  "eta_minutes": 45
}
```

Mapeamento da resposta do iFood:

| Campo MCP | Campo interno | Regra |
|---|---|---|
| `itemId` | `product_id` | obrigatório |
| `itemName` | `name` | obrigatório |
| `promotionalUnitPrice` ou `unitPrice` | `unit_price_cents` | promoção tem precedência; BRL decimal vira centavos |
| `merchant.merchantId` | `merchant_id` | obrigatório |
| `merchant.merchantName` | `merchant_name` | obrigatório |
| `deliveryMethod.promotionalFee` ou `fee` | `delivery_fee_cents` | promoção tem precedência |
| `estimatedMinutes.max` | `eta_minutes` | usa o máximo conservador |
| ausente | `other_fees_cents` | `null` |

O runtime só usa `provider="ifood_mcp"` quando a tool terminou com sucesso e o
corpo não contém `errors`.

### Localização

`searchOffers` exige coordenadas:

```json
{
  "latitude": -23.55,
  "longitude": -46.63
}
```

Uma string como `"São Paulo, SP"` não é enviada como coordenada. As regras são:

- coordenadas válidas no contexto: usar as coordenadas recebidas;
- somente string ou localização ausente, mas sandbox configurado: usar sandbox;
- ao usar sandbox: retornar `detail="sandbox_location_used"` e registrar no
  resumo da ferramenta `Localização de sandbox utilizada`;
- sem coordenadas e sem sandbox: retornar
  `unavailable/location_required`.

Filtros `VEGETARIAN`, `VEGAN` e `GLUTEN_FREE` são enviados em
`refinements.dietary`. A resposta atual de `searchOffers` não traz tags formais
que comprovem a restrição; por isso o agente deve apresentar essa limitação ao
cliente.

## 5. Endpoints do backend

| Método | Rota | Situação |
|---|---|---|
| `POST` | `/api/v1/sessions` | implementado |
| `POST` | `/api/v1/chat/messages` | implementado e conectado ao orquestrador pelo bootstrap |
| `POST` | `/api/v1/audio/transcriptions` | contrato implementado; falta provedor STT |
| `GET` | `/api/v1/agents` | implementado; exige perfil de gestor |
| `GET` | `/api/v1/sessions/{id}/snapshot` | implementado |
| `GET` | `/api/v1/sessions/{id}/history` | implementado |
| `GET` | `/api/v1/sessions/{id}/events` | SSE implementado |
| `GET` | `/api/v1/admin/overview` | implementado em memória de demo |
| `POST` | `/api/v1/orders/submit` | contrato implementado; operação real desabilitada |

## 6. Arquivos importantes

### `backend/integrations`

- `config.py`: configuração por variáveis de ambiente;
- `opencode_client.py`: cliente HTTP do OpenCode Server;
- `agent_runtime.py`: implementação de `AgentRuntimePort`;
- `errors.py`: erros normalizados;
- `offer_search.py`: busca simulada antiga/de apoio;
- `transcription.py`: contrato para um provedor de transcrição;
- `tests/`: testes do cliente, parser e runtime.

### `backend/api`

- `main.py`: inicialização executável completa;
- `app.py`: rotas FastAPI;
- `models.py`: DTOs fechados do contrato v1;
- `services.py`: adaptação entre API, orquestrador, catálogo e eventos;
- `state.py`: estado e histórico efêmeros;
- `sse.py`: formatação dos eventos SSE;
- `tests/`: testes HTTP, SSE e compatibilidade com os agentes.

### Configuração

- `opencode.json`: Gemini 2.5 Flash e MCP oficial do iFood;
- `pyproject.toml`: dependências Python;
- `PROMPT.md`: contrato definitivo do produto e dos JSONs;
- `AGENTS.md`: limites de edição das branches.

## 7. O que já está pronto na parte do Lorenzo

- [x] Cliente HTTP do OpenCode Server.
- [x] Configuração segura por ambiente.
- [x] MCP remoto do iFood declarado no `opencode.json`.
- [x] Escopo mínimo `mcp.discovery.search.read`.
- [x] Adaptador compatível com `AgentRuntimePort`.
- [x] Tradução lógica `offer_search` para `searchOffers`.
- [x] Filtros alimentares em `refinements.dietary`.
- [x] Parser de ofertas baseado no resultado bruto do MCP.
- [x] Conversão segura de BRL decimal para centavos.
- [x] Tratamento de cota, timeout, saída inválida e indisponibilidade.
- [x] Proteção contra promoção falsa de dados do modelo para `ifood_mcp`.
- [x] API HTTP conforme o contrato v1.
- [x] Persistência de eventos antes da transmissão SSE.
- [x] Reconexão por `after_seq` e `Last-Event-ID`.
- [x] Serialização de mensagens da mesma sessão.
- [x] Catálogo dos agentes conectado ao endpoint `/agents`.
- [x] Bootstrap executável em `backend.api.main:app`.
- [x] Compatibilidade testada com `feat/agents@ac7fcf1`.
- [x] 61 testes conjuntos aprovados na última validação.

## 8. O que ainda precisa ser feito pelo Lorenzo

### Prioridade 0 — provar a busca real

- [ ] Confirmar no portal do iFood que o agente está cadastrado e aprovado.
- [ ] Obter localmente `client_id` e `client_secret` OAuth do iFood.
- [ ] Confirmar liberação do escopo `mcp.discovery.search.read`.
- [ ] Confirmar conta e localização válidas no sandbox.
- [ ] Configurar o Gemini no OpenCode com `/connect`, sem versionar a chave.
- [ ] Iniciar `opencode serve` e verificar `/global/health`.
- [ ] Verificar o estado do MCP no endpoint `/mcp` do OpenCode.
- [ ] Confirmar que o identificador real de `searchOffers` aparece na descoberta
  de ferramentas.
- [ ] Executar uma busca real, somente leitura, sem carrinho ou pagamento.
- [ ] Guardar um JSON sanitizado da resposta real para conferir o parser.
- [ ] Confirmar, na resposta real, preço, promoção, taxa, ETA e campos nulos.
- [ ] Rodar o fluxo completo HTTP → agentes → OpenCode → MCP → SSE.

Bloqueio atual conhecido: sem as credenciais OAuth liberadas, o MCP responde
como não autenticado. O OpenCode não consegue criar sozinho um cliente OAuth
que o servidor do iFood não permita registrar dinamicamente.

### Prioridade 1 — finalizar a composição do projeto

- [ ] Integrar as branches `feat/agents` e `feat/integrations` por PR, sem
  copiar ou editar os contratos dos agentes.
- [ ] Conectar a implementação real de `MemoryPort` quando ela estiver pronta.
- [ ] Trocar estado e histórico efêmeros por armazenamento persistente.
- [ ] Tornar o modo da sessão configurável entre `demo` e `real`; atualmente a
  criação de sessão usa `demo` por segurança.
- [ ] Substituir a identidade fixa de demonstração por autenticação/autorização
  real para comprador e gestor.
- [ ] Testar a separação por `tenant_id` com armazenamento persistente.
- [ ] Definir com a equipe se o `uv.lock` deve ser versionado; ele está local e
  ainda não foi commitado.

### Prioridade 2 — robustez do runtime

- [ ] Medir a cota gratuita real do Gemini e registrar os limites observados.
- [ ] Adicionar retry controlado apenas para falhas marcadas como recuperáveis.
- [ ] Respeitar `Retry-After` quando o provedor informar esse cabeçalho.
- [ ] Impedir tempestade de chamadas com limite por sessão/tenant.
- [ ] Testar indisponibilidade do OpenCode, MCP e Gemini separadamente.
- [ ] Fixar ou validar uma versão compatível do OpenCode, pois a descoberta de
  ferramentas usa endpoints experimentais.
- [ ] Adicionar logs estruturados sem prompts, tokens, coordenadas ou PII.
- [ ] Criar teste de fumaça que falhe claramente quando o OpenCode não estiver
  iniciado ou o MCP não estiver autenticado.

### Prioridade 3 — áudio

- [ ] Escolher o provedor de speech-to-text.
- [ ] Implementar `TranscriptionProvider`.
- [ ] Configurar a chave somente no backend.
- [ ] Testar formatos, tamanho máximo, português brasileiro e falhas.
- [ ] Não guardar áudio bruto por padrão.
- [ ] Manter a confirmação humana para valores, quantidades e restrições.

### Prioridade 4 — carrinho e pedido

Somente começar depois da busca real estar comprovada.

- [ ] Descobrir as tools reais de carrinho/pedido liberadas ao agente.
- [ ] Solicitar somente os novos escopos estritamente necessários.
- [ ] Implementar adapters de carrinho sem duplicar a conexão MCP.
- [ ] Exigir confirmação explícita antes de qualquer operação efetiva.
- [ ] Implementar idempotência por `client_action_id`.
- [ ] Nunca tratar `202 accepted` como pedido concluído.
- [ ] Emitir `cart_changed` e `order_status_changed` somente a partir de fatos
  confirmados pela ferramenta.
- [ ] Não implementar pagamento até haver ferramenta, escopo e autorização
  explicitamente confirmados.

## 9. Como executar localmente depois de obter as credenciais

Os valores abaixo são nomes de variáveis, não valores reais. Nunca copie
segredos para este documento.

### Terminal 1 — configurar e iniciar OpenCode

Primeiro, abra o OpenCode e execute `/connect` para cadastrar a chave do Google
localmente. Depois, no PowerShell:

```powershell
$env:IFOOD_MCP_CLIENT_ID = "valor-local"
$env:IFOOD_MCP_CLIENT_SECRET = "valor-local"
$env:IFOOD_SANDBOX_LATITUDE = "-23.55"
$env:IFOOD_SANDBOX_LONGITUDE = "-46.63"
$env:OPENCODE_SERVER_PASSWORD = "senha-local"

opencode serve --hostname 127.0.0.1 --port 4096
```

As coordenadas acima são apenas exemplo. Use a localização oficial fornecida
pelo sandbox.

### Terminal 2 — iniciar o backend

Use as mesmas variáveis de configuração do servidor quando aplicável:

```powershell
$env:OPENCODE_BASE_URL = "http://127.0.0.1:4096"
$env:OPENCODE_SERVER_USERNAME = "opencode"
$env:OPENCODE_SERVER_PASSWORD = "senha-local"
$env:IFOOD_SANDBOX_LATITUDE = "-23.55"
$env:IFOOD_SANDBOX_LONGITUDE = "-46.63"

uv run --python 3.12 uvicorn backend.api.main:app --reload
```

Verificações:

```text
OpenCode: http://127.0.0.1:4096/global/health
OpenCode OpenAPI: http://127.0.0.1:4096/doc
Backend OpenAPI: http://127.0.0.1:8000/docs
```

### Testes

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --python 3.12 ruff check backend/api backend/integrations
uv run --python 3.12 pytest backend/api/tests backend/integrations/tests -q
```

## 10. Critério de conclusão do trabalho do Lorenzo

A parte do Lorenzo estará pronta para o MVP quando:

1. uma mensagem HTTP gerar uma busca `searchOffers` real;
2. a busca usar OAuth e o escopo oficial do iFood;
3. o resultado real for convertido para centavos e para o contrato dos agentes;
4. `provider="ifood_mcp"` aparecer somente com prova de sucesso;
5. a recomendação e os eventos aparecerem no snapshot, histórico e SSE;
6. falhas de cota, timeout e autenticação não derrubarem a API;
7. a origem da localização estiver explícita;
8. a memória real puder substituir a memória de demonstração;
9. áudio permanecer funcional ou retornar `STT_UNAVAILABLE` sem quebrar texto;
10. carrinho/pedido continuarem bloqueados até ferramenta, escopo e confirmação
    explícita existirem.

## 11. Regras de segurança

- Nunca enviar chave Gemini, `client_secret`, access token ou refresh token no
  chat, no Git, nos eventos ou nos logs.
- Nunca registrar payload completo do MCP se ele contiver dados pessoais.
- Nunca chamar uma resposta simulada de resposta real.
- Nunca enviar endereço, telefone, CPF ou meios de pagamento em
  `ToolTrace.summary`.
- Nunca criar carrinho, pagamento ou pedido durante o teste de busca.
- Nunca alterar frontend, agentes ou memória fora das interfaces acordadas.

## 12. Estado atual em uma frase

A estrutura técnica está pronta e testada com dados simulados: API, SSE,
orquestrador e runtime OpenCode já se conectam. O próximo passo crítico do
Lorenzo é autenticar o MCP oficial do iFood e registrar a primeira busca real e
sanitizada; depois vêm persistência, áudio e operações transacionais.
