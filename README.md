# PedIA — Escritório Virtual Multiagente (Hackathon iFood)

Chatbot vendedor que atende por **texto ou áudio**, com um **escritório de agentes de IA** trabalhando nos
bastidores: eles entendem o pedido, pesquisam no iFood (MCP real), montam e auditam propostas, escolhem a
estratégia de venda e sugerem descontos ao gestor. O gestor comercial acompanha tudo em tempo real: os
agentes, a conversa entre eles, os conflitos, as decisões e o custo de IA por cliente.

**Equipe:** Gabriel Maia · Luana Vitorino · Sarah Gurgel · Lorenzo Rudnik

---

## O que ele faz

- **Comida de restaurante**, com pessoas, orçamento, restrições alimentares (inclusive de parte do grupo),
  preferências e complementos ("parmegiana com coca e batata frita"), sempre que possível no mesmo restaurante.
- **Compra de supermercado, na hora ou agendada**: lista com quantidades e tamanhos ("arroz 5 kg, 2 feijões,
  leite e café"), "adiciona/tira", "todo sábado às 10h".
  - Na data, a cesta é refeita com os preços do dia e o cliente confirma de novo.
- **Áudio:** transcrição local com Whisper; o cliente revisa o texto antes de enviar.
- **Memória do cliente:** histórico e cadastro. "Quero o mesmo" funciona; 4 clientes fictícios para a demonstração.
- **Botão "Comprar"**: registra uma compra **simulada** e avisa o cliente.
- **Escritório do gestor:**
  - Dashboard, Painel de Agentes (grafo de comunicação) e Conflitos;
  - Análise financeira: funil, uso da IA, estratégias que mais vendem, custo de IA por cliente e % da venda.

## Arquitetura em uma imagem

```
Navegador ─► proxy :8080 ─┬─► Frontend Expo/React Native Web :8081
                          └─► API FastAPI :8000 ─► Agentes ─► OpenCode :4096 ─┬─► MCP iFood (busca)
                                                  │                           └─► Claude Haiku
                                                  ├─► Memória (SQLite, RAG em Markdown)
                                                  └─► Whisper local (áudio)
```

**10 agentes:** Orquestrador, Intérprete, Memória do cliente, Pesquisador, Curador, Planejador de compra,
Montador da cesta, Auditor, Estrategista de vendas e Especialista em descontos.

**Princípio:** a IA entende e julga; o código calcula e garante. Preço, total, orçamento, restrições e origem
dos dados são conferidos por regras, e toda resposta de IA tem uma regra de reserva.

Detalhes completos em [`docs/ARQUITETURA_COMPLETA.md`](docs/ARQUITETURA_COMPLETA.md). Os agentes, com foco
no texto do documento final, estão em [`docs/ARQUITETURA_AGENTES.md`](docs/ARQUITETURA_AGENTES.md).

## Estrutura

```
backend/
  agents/        orquestrador, especialistas, regras, demo offline (catálogo e IA simulados)
  api/           FastAPI: contrato HTTP/SSE v1, sessões, eventos, compra simulada, chat no terminal
  integrations/  runtime OpenCode (MCP iFood + IA), transcrição Whisper
  memory/        SQLite (estado e cliente), RAG comercial (knowledge/*.md), clientes fictícios
frontend/        Expo + React Native Web: chat, escritório e Análise financeira
docs/            arquitetura completa e texto dos agentes para o documento final
opencode.json    agentes do OpenCode (ifood-search, ifood-reasoning) e servidor MCP do iFood
```

## Como rodar

### Demonstração offline (sem internet, sem custo)
```bash
uv sync                                    # dependências Python (pyproject.toml)
uv run python -m backend.api.run_local     # API em modo demo na porta 8000
cd frontend && npm ci && npm run web       # Expo Web na porta 8081
cd frontend && npm run proxy               # abrir http://localhost:8080
```
Também dá para conversar só pelo terminal:
- `python -m backend.agents.demo`: só os agentes;
- `python -m backend.api.chat_cli`: pela API.

### Modo real (iFood + IA)
1. Credenciais OAuth do iFood em `backend/integrations/.local/` (`ifood-client-id.txt` e
   `ifood-client-secret.txt`). A pasta é ignorada pelo git.
2. `opencode serve --hostname 127.0.0.1 --port 4096`, com a chave do provedor de IA cadastrada no OpenCode.
3. Áudio (opcional): `pip install -r backend/integrations/requirements-stt.txt` e ffmpeg instalado.
4. API:
   ```bash
   APP_STT_PROVIDER=whisper APP_STT_MODEL=small \
   OPENCODE_PROVIDER_ID=anthropic OPENCODE_MODEL_ID=claude-haiku-5-5 OPENCODE_MODEL_VARIANT= \
   python -m backend.api.run_local --real --local-demo-admin
   ```
   - Sem endereço do cliente, as buscas usam um ponto público de teste em São Carlos/SP.
   - `--include-closed-restaurants` mostra lojas fechadas como "somente teste", para ensaios fora do horário.
5. Frontend como no modo demo: `npm run web` + `npm run proxy`.

Parâmetros úteis:
- `APP_SCHEDULE_TICK_SECONDS`: relógio das compras agendadas (padrão 30 s; `0` desliga).
- `APP_USD_BRL_RATE` e `APP_ASSUMED_MARGIN_BPS`: câmbio e margem usados no custo de IA (padrão 5,5 e 30%).
- `APP_DEMO_CUSTOMERS=0`: desliga os clientes fictícios.

## Testes
```bash
uv run pytest                              # agentes, memória, API e integrações
cd frontend && npx tsc --noEmit && npm test
```
Os testes reais (que gastam cota) só rodam com `RUN_LIVE_IFOOD=1` ou `RUN_LIVE_OPENCODE=1`.

## Limites honestos
- O MCP liberado ao time **só faz busca**: não há carrinho, pedido, pagamento nem agendamento no iFood.
  Por isso "fechado" e "Comprar" registram compras **simuladas**.
- Sessões, eventos, memória do cliente, custo de IA e agendamentos ficam na memória do processo: reiniciar
  a API apaga. Só o estado dos agentes por atendimento fica em SQLite.
- Autenticação é de demonstração (papéis fictícios de comprador e gestor).
- Política comercial, margem e o histórico dos clientes da demonstração são **fictícios** e sinalizados.
