# Atualização do projeto — 18/10/2026

> Leia antes de continuar. Este arquivo resume o estado da `main` após o merge do PR #2
> (`b6b7dbe`). As regras de trabalho continuam em `AGENTS.md`; o produto e o contrato em `PROMPT.md`.

## Novo: teste real em uma segunda máquina (18/10, madrugada)

O modo real foi reproduzido fora da máquina do Lorenzo, com a `main` (`8cf34c3`), OpenCode 1.19.3,
chave Gemini nova e OAuth iFood próprio (`opencode mcp list` → `ifood connected (OAuth)`;
`GET /mcp` do OpenCode → `connected`).

| Busca real pela API (`APP_RUNTIME_MODE=real`) | Tempo | Resultado |
|---|---|---|
| "quero pizza para 2 pessoas até R$ 150" | 12 s | La Sapore Pizza, 2x Pizza Grande, R$ 69,98; 2 recomendações `ifood_mcp`; aviso de taxa de serviço |
| Mesmo pedido com `restrictions: ["vegetariana"]` | 20 s | Meta Pizza, 2x Pizza Doce Caramelita, R$ 89,86; `ifood_mcp`; aviso "não comprovada"; **a calabresa sumiu** |

- Sessões criadas com `mode: "real"`; comprador recebeu só `session_started`, `chat_message` e
  `recommendations_ready` — nenhum evento `admin` vazou.
- Nenhum carrinho, voucher, pedido ou pagamento.
- O filtro `refinements.itemRestrictions` **pareceu funcionar** (só itens sem carne), em **uma** amostra.

**Ainda não comprovado / problemas encontrados neste teste:**

1. **Painel do gestor bloqueado em modo real:** em `APP_RUNTIME_MODE=real`, `GET /agents` e os
   eventos `admin` respondem 403 mesmo com `X-Demo-Role: admin` (por desenho, o cabeçalho só vale no
   demo). **Sem isso, o escritório visual não mostra nada numa apresentação em modo real.**
   → Lorenzo: opção explícita (ex.: `APP_DEMO_ADMIN=1`, restrita a `127.0.0.1`) para liberar o gestor
   de demonstração no modo real local.
2. "**Uma** opção vegetariana" (faz 2 buscas seguidas) não foi testada ao vivo; risco de timeout.
3. Relevância: o pedido vegetariano trouxe pizzas doces para "pizza para 2 pessoas".
4. Cota Gemini: foram usadas 2 buscas da chave nova; segue limitada.

## O que entrou na `main`

O backend do MVP está integrado e funcionando de ponta a ponta em modo demo:

```
Frontend → API FastAPI (HTTP/SSE) → agentes → runtime OpenCode → Gemini → MCP iFood
```

| Pasta | Responsável | Estado |
|---|---|---|
| `backend/api/**` | Lorenzo | Sessões, mensagens, `initial_context`, catálogo, snapshot, histórico, SSE, perfil de gestor da demo |
| `backend/integrations/**` | Lorenzo | Runtime OpenCode + MCP iFood (`searchOffers`), modo `demo`/`real` |
| `backend/agents/**` | Claude Code | Orquestrador + pesquisador, planejador, auditor, estrategista de vendas e especialista em descontos; demo offline |
| `backend/memory/**` | Codex da memória | **Ainda não implementado**; a API usa memória temporária |
| Frontend | Equipe de design | Fora deste repositório de backend |

Testes na `main`: `pytest` (57 aprovados, 1 teste real opt-in pulado) e
`python3 -m unittest discover -s backend/agents/tests -t .` (65 aprovados).

## Como rodar

```bash
# API em modo demo (padrão): catálogo fictício, sem iFood/Gemini/internet
uvicorn backend.api.main:app --port 8000

# API em modo real: exige `opencode serve --hostname 127.0.0.1 --port 4096` rodando na pasta do
# projeto, credenciais locais e OAuth feito (ver backend/api/README.md). Sem as coordenadas abaixo,
# a busca falha com location_required. (No Windows: `set VAR=valor` em linhas separadas.)
APP_RUNTIME_MODE=real IFOOD_SANDBOX_LATITUDE=-23.5505 IFOOD_SANDBOX_LONGITUDE=-46.6333 \
  IFOOD_FALLBACK_LOCATION_SOURCE=public_test uvicorn backend.api.main:app --port 8000

# Plano B: demonstração só no terminal, sem API nem rede
python3 -m backend.agents.demo --roteiro --escritorio
```

- Gestor na demo: cabeçalho `X-Demo-Role: admin` (só no modo demo; não é autenticação real).
- Contrato HTTP/SSE: `PROMPT.md` §15 e `docs/CONTRATO_INTERFACE.md`, incluindo `initial_context`.

## O que foi comprovado de verdade

- Fluxo completo em modo demo pela API: sessão → mensagem → 6 agentes → recomendação → SSE.
- **Três** buscas **reais** no MCP do iFood pela API, em duas máquinas diferentes (Lorenzo: 5 ofertas, 3 recomendações; segunda máquina: 2 buscas, ver topo), sem carrinho, pedido ou pagamento.
- Comprador não recebe eventos internos do gestor.
- Nenhuma credencial versionada: `opencode.json` só referencia arquivos locais ignorados pelo Git.

## O que ainda NÃO está pronto

1. **Filtro vegetariano ao vivo** (`refinements.itemRestrictions`) — funcionou em uma amostra (ver acima); falta testar "uma opção vegetariana" e repetir.
2. **Cota do Gemini**: o modelo atual permite cerca de 20 solicitações. A chave do Lorenzo estourou após a primeira busca; uma chave nova aguentou as 2 buscas do teste. Economize chamadas reais.
3. **Memória persistente** (`backend/memory`).
4. **Autenticação real** de comprador e gestor.
5. **Transcrição de áudio** (provedor STT).
6. **Pedidos e pagamento**: desabilitados até haver implementação, permissões e confirmação explícita do cliente.
7. **Interface conectada à API**: ainda não testada com o frontend.

## Próximos passos por responsável

- **Todos:** atualizem sua branch a partir da `main` antes de continuar. Não editem a pasta de outro responsável.
- **Lorenzo (`feat/integrations`):** **prioridade 1: liberar o gestor de demonstração no modo real local** (item 1 do teste acima); depois testar "uma opção vegetariana" ao vivo e a troca futura para Claude no OpenCode. Mudanças entram por novo PR.
- **Codex da memória (`feat/memory`):** implementar `MemoryPort` (`backend/agents/ports.py`: `load` / `save_patch` com `RevisionConflict`) em SQLite e substituir `backend/api/session_memory.py` na composição (`build_application(memory=...)`).
- **Claude Code (`feat/agents`):** economia de chamadas ao runtime (reaproveitar ofertas em mensagens seguintes) e ajustes após o teste vegetariano real.
- **Frontend:** consumir a API pelo contrato v1; modo demo disponível para desenvolver sem iFood.

## Regras que continuam valendo

- Merge de código na `main` somente com autorização humana, via PR. Exceção autorizada: este
  `ATUALIZACAO.md` é atualizado direto na `main` para comunicar o time (dê `git pull` e leia antes de
  cada tarefa).
- Nunca colocar credenciais, tokens ou dados pessoais em código, commits, logs ou eventos.
- Dados de demonstração sempre marcados como `demo`; nunca apresentar simulação como dado real do iFood.
