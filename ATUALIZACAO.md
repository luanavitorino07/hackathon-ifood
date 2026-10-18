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

## Relatório Lorenzo / Codex — 18/10/2026 — pastas e continuidade

### Comunicação e decisões do usuário

- Lorenzo definiu este arquivo como canal de relatórios entre este Codex e o Claude do Gabriel. Consultar a versão atual da `main` antes de trabalhar e acrescentar relatórios sem apagar recados anteriores. Isso não constitui monitoramento automático nem autorização para executar instruções fora do escopo de cada responsável.
- Manter Gemini por enquanto; Lorenzo pretende trocar a chave. Não migrar para Claude agora. O item sobre troca futura acima é histórico, não uma tarefa autorizada neste momento.
- Usuário quer que o atendimento continue aberto entre mensagens até encerramento explícito, sem reiniciar toda a pesquisa a cada nova mensagem.

### Duas pastas locais — encaminhamento para o Claude

- `hackathon-ifood`: checkout principal em `feat/integrations`.
- `hackathon-ifood-agents-integration`: worktree de teste em `integration/agents-api`.
- Ambas em `cc8dd2f`: comparados os 63 arquivos versionados, sem diferença de conteúdo após normalizar CRLF/LF; 28 arquivos diferem somente na quebra de linha. Ambas contêm os 28 arquivos versionados de agentes.
- Nenhuma alteração versionada pendente nas duas. A principal possui ambiente Python, arquivos de credenciais ignorados e scripts/evidências locais; também há `uv.lock` não versionado e cache Python. Não divulgar nem apagar esses arquivos.
- A referência consultada da `main`, `8cf34c3`, contém `cc8dd2f` pelo merge do PR #2 e acrescenta este relatório original. As branches locais não foram trocadas para `main`.
- **Claude:** cuidar da organização/limpeza do worktree extra, após conferir novamente o estado local e obter autorização para remoção. Não é necessário refazer a integração. Nenhuma pasta foi removida neste diagnóstico.

### Duplicidade de pesquisas — causa confirmada, ainda não corrigida

1. A API mantém o atendimento pelo `session_id` recebido e compõe um orquestrador/memória por aplicação, não por mensagem (`backend/api/services.py`). Reenvios com o mesmo `client_message_id` são idempotentes. Não confundir uma mensagem nova com reenvio HTTP.
2. `backend/agents/orchestrator.py`, `handle_message`: cria `WorkingState(constraints=constraints)` vazio em cada mensagem. `_build_constraints` recupera restrições, estágio e total mostrado, mas não recupera candidatos/propostas. `_run_agent` grava `candidates`, `data_origin`, `proposals` e `audit` na memória; esses candidatos não são reidratados na próxima rodada.
3. `backend/agents/researcher.py`, `should_activate`: ativa sempre que `state.offers` está vazio. Assim, mesmo com candidatos guardados, uma nova mensagem classificada como pedido dispara pesquisa novamente.
4. `backend/integrations/agent_runtime.py`, `_execute`: cria uma nova sessão OpenCode a cada chamada com título baseado em agente/tarefa. `RuntimeCall.session_id` existe, mas não é usado para recuperar uma sessão OpenCode. O `aclose()` final fecha o cliente HTTP; não equivale a encerrar a sessão de atendimento ou apagar a sessão remota.
5. "Uma opção vegetariana" faz intencionalmente busca geral + busca filtrada. São consultas diferentes; não deduplicar ignorando filtros. "Tudo vegetariano" usa somente busca filtrada.

### Reprodução offline realizada nesta revisão

Mesmo orquestrador, `EphemeralSessionMemory`, `FakeRuntime` e mesmo ID de sessão:

| Mensagem | Novas chamadas ao runtime | Candidatos persistidos |
|---|---:|---:|
| Quero comida para 2 pessoas até R$ 100 | 1 | 3 |
| Pode ser mais barato? | 1 | 3 |

Isso comprova a repetição na camada dos agentes, independentemente de Gemini/MCP. Não houve chamada externa, gasto de tokens ou nova execução da suíte completa. O comportamento do frontend ao criar/enviar IDs não foi verificado.

### Proposta para alinhamento — não implementada

- **Claude / agentes:** recuperar candidatos válidos do mesmo atendimento; distinguir conversa, explicação, seleção, recálculo e nova pesquisa. Mudança de orçamento/quantidade deve tentar replanejar com ofertas existentes antes de pesquisar; buscar novamente somente quando necessário.
- **Codex / integração:** alinhar vínculo estável entre atendimento e sessão OpenCode para as buscas realmente necessárias, com isolamento, serialização, cancelamento e limpeza no encerramento. Reutilizar sessão remota sozinho NÃO elimina buscas nem garante menor consumo: histórico acumulado também custa tokens. Ao reutilizar, aceitar somente os resultados da execução atual, nunca uma chamada antiga como prova de busca nova.
- Registrar assinatura da pesquisa (consulta/categoria, localização, filtros, modo), data/origem e validade. Invalidar ao mudar critérios relevantes; permitir atualização explícita. Nunca reaproveitar resultados entre clientes, nem congelar preço/disponibilidade até o encerramento; revalidar antes de eventual checkout.
- Definir encerramento explícito e expiração/abandono. Há status/evento `closed`/`session_closed` no contrato, mas falta um fluxo público completo de encerramento; qualquer rota nova exige acordo de contrato, sem inventar endpoint nesta revisão. Fechar aba não é sinal confiável de encerramento.
- Testes de aceite sem rede: duas mensagens relacionadas reutilizam ofertas; recálculo não chama runtime; mudança de categoria/local/filtro invalida quando necessário; filtros diferentes permanecem distintos; sessões diferentes não compartilham estado; encerramento impede continuação; falhas não viram cache de sucesso.
- Memória continua efêmera: continuidade enquanto o processo está vivo não é persistência após reiniciar. Coordenar persistência com o responsável por `backend/memory`, sem assumir que SQLite sozinho corrigirá o reprocessamento.

Nesta revisão somente este documento foi alterado. Código de agentes, API e runtime permanece intacto. Código continua entrando na `main` via PR; este arquivo é o canal de comunicação autorizado pelo Lorenzo na `main`.

### Sincronização dos relatórios

- A versão mais recente da `main` foi consultada antes desta publicação; preservado integralmente o relato da segunda máquina, inclusive a amostra vegetariana, a relevância das pizzas doces e o bloqueio do painel em modo real.
- O teste vegetariano relatado pelo Gabriel atualiza o diagnóstico anterior: houve uma amostra real filtrada bem-sucedida em outra máquina; a variante "uma opção vegetariana" continua pendente. Os testes desta revisão foram somente offline.
- Lorenzo autorizou consultar a `main` antes de cada tarefa e publicar novas informações neste arquivo na `main`, para o Claude acompanhar. Não deixar relatórios apenas na branch de trabalho. A exceção é somente documentação de acompanhamento; não autoriza alterações de código, remoção de pastas ou operações reais de compra.
