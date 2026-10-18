# Atualização do projeto — 18/10/2026

> Leia antes de continuar. Este arquivo resume o estado da `main` após o merge do PR #2
> (`b6b7dbe`). As regras de trabalho continuam em `AGENTS.md`; o produto e o contrato em `PROMPT.md`.

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

# API em modo real: exige OpenCode rodando e credenciais locais (ver backend/api/README.md)
APP_RUNTIME_MODE=real uvicorn backend.api.main:app --port 8000

# Plano B: demonstração só no terminal, sem API nem rede
python3 -m backend.agents.demo --roteiro --escritorio
```

- Gestor na demo: cabeçalho `X-Demo-Role: admin` (só no modo demo; não é autenticação real).
- Contrato HTTP/SSE: `PROMPT.md` §15 e `docs/CONTRATO_INTERFACE.md`, incluindo `initial_context`.

## O que foi comprovado de verdade

- Fluxo completo em modo demo pela API: sessão → mensagem → 6 agentes → recomendação → SSE.
- Uma busca **real** no MCP do iFood pela API (5 ofertas, 3 recomendações), sem carrinho, pedido ou pagamento.
- Comprador não recebe eventos internos do gestor.
- Nenhuma credencial versionada: `opencode.json` só referencia arquivos locais ignorados pelo Git.

## O que ainda NÃO está pronto

1. **Filtro vegetariano ao vivo** (`refinements.itemRestrictions`) — não confirmado com o iFood. Prioridade do próximo teste real.
2. **Cota do Gemini**: o modelo atual permite cerca de 20 solicitações; o fluxo real estourou após a primeira busca. Economize chamadas reais.
3. **Memória persistente** (`backend/memory`).
4. **Autenticação real** de comprador e gestor.
5. **Transcrição de áudio** (provedor STT).
6. **Pedidos e pagamento**: desabilitados até haver implementação, permissões e confirmação explícita do cliente.
7. **Interface conectada à API**: ainda não testada com o frontend.

## Próximos passos por responsável

- **Todos:** atualizem sua branch a partir da `main` antes de continuar. Não editem a pasta de outro responsável.
- **Lorenzo (`feat/integrations`):** teste real vegetariano; repetir poucas buscas reais após renovar a cota; troca futura para Claude no OpenCode. Mudanças entram por novo PR.
- **Codex da memória (`feat/memory`):** implementar `MemoryPort` (`backend/agents/ports.py`: `load` / `save_patch` com `RevisionConflict`) em SQLite e substituir `backend/api/session_memory.py` na composição (`build_application(memory=...)`).
- **Claude Code (`feat/agents`):** economia de chamadas ao runtime (reaproveitar ofertas em mensagens seguintes) e ajustes após o teste vegetariano real.
- **Frontend:** consumir a API pelo contrato v1; modo demo disponível para desenvolver sem iFood.

## Regras que continuam valendo

- Merge na `main` somente com autorização humana, via PR.
- Nunca colocar credenciais, tokens ou dados pessoais em código, commits, logs ou eventos.
- Dados de demonstração sempre marcados como `demo`; nunca apresentar simulação como dado real do iFood.
