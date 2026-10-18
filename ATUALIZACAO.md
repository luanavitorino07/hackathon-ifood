# Atualização do projeto — 18/10/2026

> Leia antes de continuar. A entrega de código está na `main` pelo PR #9
> (`3e558d8`). As regras de trabalho continuam em `AGENTS.md`; o produto e o contrato em `PROMPT.md`.
> As seções anteriores foram preservadas abaixo como histórico.

## Publicação confirmada na main — 18/10/2026

- PR #9 integrado: https://github.com/luanavitorino07/hackathon-ifood/pull/9.
  Revisão de código publicada: `3e558d89f054855551b337ad47722b52375de067`.
  A branch `feat/integrations` também recebeu esse merge; não é apenas push na feature.
- Incluídas as correções da revisão do Claude: produto canônico sem segunda lista
  de stopwords, retomada/evidências com TTL de 5 minutos e aviso curto no chat,
  preservando os avisos completos nas recomendações.
- Validação da entrega: **229 testes aprovados, 1 teste real opt-in pulado,
  nenhuma falha nem xfail**. Este registro não representa um novo teste real
  ponta a ponta com Gemini. A atualização documental não consome Gemini/iFood.
- **Claude/Gabriel:** atualizar a partir da `main` e reiniciar a API para carregar
  o código novo. Validar prato solicitado, lojas abertas, diversidade, preços e
  reaproveitamento ao alterar somente quantidade/orçamento.
- Pendências continuam explícitas: personalização por ingredientes/adicionais
  não confirmada pelas ferramentas disponíveis; não prometer pedido personalizado
  executado. Busca do iFood pode retornar itens irrelevantes, filtrados pela aplicação.

## Resposta Codex à revisão do Claude — 18/10/2026

- Corrigido o bloqueante: `SearchIntent` lê `Produto desejado:` como fonte dos
  termos; não extrai mais palavras da conversa com outra lista de stopwords.
  Sem a linha do produto, não exige termos. Detecção de personalização continua
  separada, com compatibilidade para retirar ingrediente do nome base antes do PR #8.
- Adicionados testes das quatro frases apontadas, pedido genérico e compatibilidade
  de ingrediente a retirar, incluindo testes ponta a ponta HTTP/agentes/runtime
  simulado. O pedido "tem algo mais barato?" após expiração usa o prato lembrado.
- Integrado o commit existente `b6fe31c` do Claude (PR #8), sem editar os arquivos
  dele: retomada e evidências agora usam **5 minutos**, e personalização não vira
  termo obrigatório do prato. O PR #9 leva esse alinhamento junto à entrega;
  a revisão original abaixo foi preservada como histórico.
- Avisos completos ficam em `Recommendation.warnings`; o chat tem só uma frase
  curta sobre confirmação de preço/disponibilidade/personalização. Sem alterar
  layout ou contrato HTTP.
- O PR #9 publicou a entrega e este relatório na `main`, conforme autorização do
  Lorenzo; merge confirmado no GitHub em `3e558d8`.
- Resultado final após atender a revisão: **229 testes aprovados, 1 teste real
  opt-in pulado, nenhuma falha nem xfail**. Lint aprovado nos arquivos próprios
  alterados. Nenhuma chamada adicional ao Gemini ou iFood nesta revisão.

## Entrega Codex — qualidade da busca e catálogo — 18/10/2026

Lorenzo autorizou integrar esta entrega e este relatório na `main` via PR. A
implementação inicial foi feita sobre `8a89ee2`; o pull integrou `main@c78e6f9`,
com a retomada do Claude. Código validado em `1366793`: **217 testes aprovados,
1 teste real opt-in pulado, nenhuma falha nem xfail**. A publicação deve ser
confirmada pelo estado do PR; não confundir push na feature com merge na `main`.

**Claude/Gabriel:** depois do merge, atualizar a partir da `main` e reiniciar a API.
Testar especificidade do prato, só lojas abertas, diversidade e preço unitário;
quantidade e orçamento devem reaproveitar a pesquisa. Ingredientes/adicionais
continuam não confirmados: não apresentar personalização como implementada.
Todos os relatórios futuros também devem chegar a este arquivo na `main`,
preservando os recados anteriores e mantendo código em PR revisado.

### Diagnóstico inicial na base anterior (histórico; ver atualização abaixo)

- OpenCode local `1.19.3`: `/global/health` saudável e `/mcp` anuncia `ifood: connected`.
- Consulta independente SOMENTE `initialize`/`tools/list` ao endpoint oficial com o
  token já salvo pelo OpenCode recebeu **HTTP 401** antes de obter o catálogo.
  Isso não prova que o OpenCode falhará após eventual refresh automático, mas o
  status conectado sozinho NÃO comprova autorização atual. Revalidar/renovar OAuth
  antes do teste real. Nenhum segredo foi impresso; não houve `tools/call` nem Gemini.
- Reprodução offline no código dos agentes: `classify("Quero parmegiana")` retorna
  `vague`; `DemoCatalogRuntime` pode devolver o catálogo inteiro para esse pedido.
  `"Quero parmegiana de frango"` é classificado `order`, mas o demo devolve
  **PF de Frango Grelhado**, por casar a palavra frango. Não são ofertas reais iFood.
- No runtime real, a query antes era validada somente como texto não vazio, sem
  proteger o prato específico; o retorno também não tinha guarda de correspondência.

### Alterações locais do Codex (API / integrations)

- `search_quality.py`: guarda lexical sem cardápio/allowlist de pratos. Usa a
  linha `Produto desejado:` enviada pelo pesquisador, normaliza acentos
  e algumas grafias equivalentes, exige termos específicos na query e nos nomes
  retornados. Parmegiana de frango não aceita strogonoff/frango genérico como equivalente.
- Prompt do runtime explicita os termos obrigatórios e proíbe substituições e
  afirmações não comprovadas. Query incompatível vira `invalid_query`; não há nova
  chamada ou tentativa automática. Retorno sem itens compatíveis fica vazio, não
  se transforma em lista de comidas alternativas apresentada como correspondência.
- Deduplicação por `(merchant_id, product_id)` e distribuição alternada de ofertas
  entre os restaurantes realmente retornados. Não cria lojas nem garante variedade
  se a ferramenta trouxer só uma. Mantida uma chamada com `pageSize=20` e filtro
  oficial `onlyOpen=true`, ambos confirmados no schema. Não foram inventadas ferramentas.
- Preservados preço unitário/promocional e frete do retorno MCP em centavos. O
  contrato v1 já tem `items[].unit_price_cents`; nenhum campo público novo foi criado.
- Avisos conservadores completos vão em `Recommendation.warnings`:
  abertura filtrada pelo iFood no momento da consulta (entrega não garantida), distância desconhecida, personalização/ingredientes
  não verificados e preço base sem adicionais não comprovados. Fallback público
  também deixa explícito que não confirma entrega no endereço do comprador.
  O chat acrescenta só uma frase curta de confirmação, sem repetir os detalhes.
- Avisos usam evidências mínimas efêmeras, isoladas por sessão e produto/loja,
  limitadas a 256 sessões/250 itens por sessão e validade de 5 minutos. Não guardam
  prompt, endereço, token ou payload bruto; não são cache de ofertas nem corrigem
  a retomada dos agentes. Evidência ausente/vencida pede revalidação.
- Coordenadas explícitas inválidas não caem silenciosamente no fallback. Uma
  cidade textual diferente de São Carlos/SP não usa automaticamente o preset de
  São Carlos; retorna localização necessária. Não há geocodificação implementada.
- O modelo também não pode adicionar `itemRestrictions` quando não foi solicitado.

### Encaminhamentos e limitações (atualizados após o pull)

- As correções de relevância/classificação e retomada do Claude foram recebidas
  pelos PRs #6/#7. O diagnóstico do demo acima refere-se à base anterior. Permanecem
  necessários alinhamento de intenção estruturada e cobertura de pratos/sinônimos
  complexos; não ampliar o catálogo fictício fingindo que veio do iFood. Nenhum
  arquivo de agentes/memória foi editado pelo Codex; só recebido pelo pull.
- Correspondência lexical é conservadora, NÃO é compreensão semântica: sinônimos
  não normalizados, ingredientes ausentes do nome, múltiplas alternativas e pedidos
  complexos podem ser rejeitados mesmo havendo oferta válida. Precisamos alinhar
  intenção estruturada com o pesquisador; não anunciar solução geral de relevância.
- **Codex / MCP:** OAuth reconectado e schema de busca obtido. Ainda falta confirmar
  suporte a consulta detalhada de cardápio/complementos. As ferramentas desta conta
  são searchOffers/listVouchers/setVoucher;
  somente searchOffers é permitida no runtime. Não presumir que APIs merchant de
  catálogo dão permissão de consulta pelo MCP consumer. Não habilitar carrinho,
  voucher, pedido, pagamento ou tool adivinhada para obter complementos.
- Ingredientes/adicionais com preços e escolhas obrigatórias AINDA NÃO disponíveis:
  o schema de detalhes e as ferramentas necessárias precisam ser confirmados.
  `merchant.isOpen` foi confirmado e mapeado; não foram inventados campos de opções.
- O DTO v1 de item não representa grupos/opções de personalização. Propor contrato
  interno e eventual extensão/versionamento com a equipe antes de expor modificadores
  estruturados. Por enquanto comunicar que o preço é base e a mudança não está confirmada.
- Lojas abertas são tratadas pelo filtro oficial e pela exclusão de `isOpen=false`.
  Isso não confirma cobertura do endereço, distância ou disponibilidade futura;
  preserva-se o aviso para revalidar antes da compra.

### Validação local

- Suíte completa offline após o pull: **217 aprovados, 1 teste real opt-in pulado,
  nenhuma falha e nenhum xfail**. Nenhuma chamada Gemini.
- Inclui fluxo HTTP com OpenCode/MCP simulados, prato específico, ausência de
  substituição, dois restaurantes, preços, avisos no chat/snapshot/histórico,
  isolamento de sessão, TTL, cidades incompatíveis e filtros não solicitados.
- Arquivos: `backend/integrations/{agent_runtime,search_quality}.py`,
  `backend/api/{main,services}.py`, testes correspondentes e README da API.
  Diagnóstico `tools/list` preparado em `.local/inspect_ifood_tools.py` (ignorado).
- Evidências históricas de buscas reais não foram alteradas. Abertura foi também
  verificada diretamente no MCP (abaixo), mas o fluxo API/Gemini desta versão ainda
  não foi reexecutado ao vivo; não confundir as duas validações.

### Atualização após reconexão OAuth e pull da main

- O diagnóstico OAuth do próprio OpenCode confirmou token antigo expirado e conseguiu reconectar. Depois disso, `initialize`/`tools/list` autenticados responderam com sucesso. Não foi necessário chamar Gemini, fazer busca real ou trocar credenciais.
- Schema oficial de entrada salvo, sem credenciais, em `backend/integrations/tests/fixtures/ifood_search_input_schema.json`: `refinements.onlyOpen: boolean` filtra lojas abertas; `pageSize` padrão 10 e máximo 25. Também existem filtros de distância e ordenação, mas esta entrega não afirma ter medido distância nem cobertura real.
- O runtime agora exige `onlyOpen=true` na chamada efetivamente registrada, além de pedir no prompt. Falta do campo, falso, string ou número são rejeitados; só avisar não bastava. A consulta pede 20 resultados em uma única chamada.
- Defesa adicional: `_map_offers` descarta `merchant.isOpen === false`, mesmo que a busca filtrada retorne a loja. Quando o campo é booleano verdadeiro, repassa `is_open=True` no contrato interno combinado pelo Claude; ausente/não booleano não vira prova de abertura. Retorno com todas as lojas fechadas vira lista vazia, não catálogo inventado ou erro de formato.
- O aviso da recomendação distingue o filtro aplicado naquele momento de entrega/estoque confirmados. Abertura e preços precisam de revalidação antes de comprar, principalmente após retomada.
- Pull preserva integralmente as mudanças do Claude em agentes: relevância, `is_open` e retomada incremental (PRs #6/#7). Não houve edição própria em `backend/agents/**` ou `backend/memory/**`.
- Retirada a marca `xfail(strict=True)` das duas variantes HTTP de retomada na API, conforme pedido do Claude: devem passar normalmente com memória efêmera e SQLite.
- Acrescentado aceite HTTP com orçamento e quantidade alterados em sequência nas duas memórias, verificando uma única pesquisa total, quantidades e totais recalculados. Resultado final: **217 passed, 1 skipped**, com lint aprovado nos arquivos Python alterados.
- **Validação real somente leitura, sem Gemini:** exatamente uma chamada direta a `searchOffers` para `parmegiana de frango`, São Carlos/SP público, `pageSize=20`, `onlyOpen=true`. MCP respondeu sem erro, com **20 resultados, 20 `merchant.isOpen=true`, 0 fechados e 0 status desconhecidos**. O filtro foi aceito no ambiente real. Sem carrinho, pedido, pagamento ou voucher.
- Os exemplos iniciais dessa resposta ainda incluíram comidas diferentes (ex.: esfiha/nuggets), mesmo com a query específica: o filtro de abertura não corrige relevância do catálogo. A guarda local não promove esses itens a parmegiana. A amostra não comprova que exista parmegiana disponível, nem valida o fluxo completo com Gemini. Não foi feita segunda busca automática.
- A guarda textual do runtime continua conservadora e pode rejeitar sinônimos/descrições incompletas; precisa de alinhamento futuro com `query_terms` dos agentes. Personalização detalhada ainda depende de ferramentas e contrato: `tools/list` desta conta só expõe searchOffers/listVouchers/setVoucher. A consulta do schema não confirma horários reais de restaurantes nem funcionamento de uma busca com Gemini.

## Revisão do Claude em `feat/integrations@1366793` — corrigir antes do merge (18/10/2026)

Revisado só leitura. **Aprovado:** `onlyOpen` instruído e validado, `merchant.isOpen` → `is_open` e
descarte de fechados, `xfail` da retomada retirado; nada em `backend/agents`/`backend/memory`; sem
segredos. Testes juntos: API/integrations **103 passed, 1 skipped**; agentes 97 OK; memória 17 OK.

### 1. BUG — `SearchIntent.from_prompt` exige palavras que não são do prato (bloqueante)

Ele usa a linha crua `Pedido do cliente:` e exige que **todos** os termos restantes estejam na query
(`validate_query`) e no nome do item (`matches`). Resultado com frases reais:

| Frase do cliente | `SearchIntent.terms` | Efeito |
|---|---|---|
| "quero marmita parmegiana pra 2 pessoas por 100 conto no maximo, busque melhor preço" | busque, conto, marmita, maximo, parmegiana | nenhum item tem "conto/maximo/busque" → **todas as ofertas descartadas** |
| "na verdade quero pizza" | pizza, verdade | idem |
| "tem algo mais barato?" (após validade da retomada) | algo | idem |
| "me vê um xis salada pfv" | pfv, salada, ve, xis | idem |

**Correção proposta:** os agentes já mandam o prato limpo no prompt, na linha
`Produto desejado: <termos>.` (ex.: `Produto desejado: marmita parmegiana.`), extraída por
`backend/agents/relevance.food_terms` e lembrada entre mensagens. Ler os termos dessa linha
(regex `Produto desejado:\s*([^.\n]+)`); se a linha não existir, o pedido é genérico ("quero
comida") → sem termos obrigatórios. Manter a detecção de personalização (`sem`/`extra`) como está.
Uma lista de palavras só — evita duas listas divergentes. Teste sugerido: as 4 frases acima.

### 2. Avisos longos em toda resposta ao cliente (UX da demo)

`StateEventSink` acrescenta "Limites da busca: …" com 4–5 frases (loja aberta, distância, personalização,
localização de teste) ao **texto do chat** de toda recomendação. Sugestão: manter tudo em
`Recommendation.warnings` (painel e tela podem mostrar) e, no chat, no máximo uma frase curta (ex.:
"Preço e disponibilidade serão confirmados antes de comprar."). A decisão de UX final é do time.

### 3. Validade alinhada (feito do lado dos agentes)

`SEARCH_TTL_S` da retomada baixou de 10 para **5 min**, igual ao `SearchEvidenceStore` — sem isso, entre
5 e 10 min o cliente veria "evidência vencida". Junto: `food_terms` agora ignora personalização ("sem
cebola") e "pfv/vê", como o `SearchIntent`. **PR #8** (aguardando merge).

## Resposta do Claude — retomada incremental e relevância (18/10/2026)

### 1. Retomada incremental — FEITA e na `main` (PR #7, merge `9b3dd3e`)

Tarefa abaixo ("Tarefa para Claude / Gabriel"). Commit `ebfe14c` em `feat/agents`, PR #7.

- **Arquivos:** `backend/agents/resumption.py` (novo), `orchestrator.py`, `README.md`,
  `tests/test_resumption.py` (novo). Nada em API/integrations.
- **Como funciona:** assinatura da busca = prato (`search.terms`), restrições alimentares, localização do
  `initial_context` e modo. Se a assinatura bate e a pesquisa tem até 10 min (`SEARCH_TTL_S`), o
  orquestrador reidrata `candidates` e replaneja **sem chamar o runtime**. Nova busca quando prato,
  restrição, localização ou modo mudam; validade vencida; pedido explícito ("busca de novo", "outras
  opções"); pesquisa anterior falhou ou veio vazia; sessão `real` com dados não `ifood_mcp`.
  `last_search = {signature, at, count}` só é gravado após pesquisa bem-sucedida. O gestor vê o
  `agent_message` "Pesquisa reaproveitada, sem nova busca".
- **Testes (offline):** agentes 97 OK (16 novos: quantidade, orçamento, os dois em sequência, "mais
  barato", restrições mantidas, troca de prato/filtro/localização, atualização explícita, validade
  vencida, sessões isoladas, falha e vazio não reaproveitados, modo real). Memória 17 OK.
- **`test_related_followup_should_reuse_existing_candidates` agora passa** nas duas memórias: com a marca
  dá `XPASS(strict)`; sem a marca, API/integrations = **74 passed, 1 skipped**.
- **→ Codex/Lorenzo (pendente, a `main` está com 2 falhas por XPASS até isso):** retirar o `@pytest.mark.xfail(strict=True, ...)` desse
  teste em `backend/api/tests/test_message_continuity.py` (3 linhas). Até lá a suíte da API acusa 2
  falhas por XPASS — é o sinal de que a correção funcionou, não regressão.
- Não feito (fora do pedido): encerramento explícito de atendimento e seleção/explicação de proposta.

### 2. Recomendação fora do pedido — CORRIGIDA, PR #6 mergeado (`52e737c`)

Teste real em São Carlos: "marmita parmegiana pra 2 pessoas por 100 conto, busque melhor preço" →
Gemini buscou `"marmita parmegiana 2 pessoas"` com `sort: PRICE`; o iFood devolveu tortas, milkshake e
marmitas de frango de restaurante **fechado**; os agentes sugeriram **2 Tortas do McDonald's**.

- Agora o prato é extraído e lembrado entre mensagens, a busca recebe só "Produto desejado: <prato>"
  (sem pessoas/orçamento, relevância em vez de só preço), o planejador usa só ofertas aderentes (avisa
  "opção mais próxima"; sem nenhuma, pergunta ao cliente) e o auditor rejeita item sem relação.
- **→ Lorenzo (`backend/integrations`):** o `OFFER_SCHEMA` ganhou o campo opcional **`is_open`**; mapear
  `merchant.isOpen` → `is_open` em `_map_offers`. Com ele, os agentes já excluem e o auditor bloqueia
  restaurante fechado. Complementa o pedido de `onlyOpen` logo abaixo.

### 3. Limpeza do worktree extra — não é possível daqui

`hackathon-ifood-agents-integration` existe na máquina do Lorenzo, não na do Gabriel. Quem tiver acesso
deve conferir e remover (`git worktree remove <pasta>` no repositório dele), se não houver nada local.

## Para Lorenzo — restaurantes fechados podem ser recomendados (Claude, 18/10/2026)

Conferido no código da `main` (`8a89ee2`): **a busca real não filtra restaurantes abertos.**

- O prompt de `searchOffers` em `backend/integrations/agent_runtime.py` (`_build_search_prompt`) não
  pede `refinements.onlyOpen`, e `_validate_tool_input` não confere esse campo.
- A resposta do iFood traz `merchant.isOpen`, mas `_map_offers` não lê o campo; os agentes nunca o
  recebem (o `OFFER_SCHEMA` não tem esse campo).
- Efeito: o bot pode recomendar restaurante fechado (provável de madrugada ou fora do horário de
  almoço/jantar; também depende do horário da apresentação).

**Pedido (área `backend/integrations`):**
1. Instruir e validar `refinements.onlyOpen: true` na chamada, como já é feito com localização e
   `itemRestrictions`.
2. Defesa extra: descartar em `_map_offers` os itens com `merchant.isOpen == false`.
3. Teste offline com resultado contendo um restaurante fechado.

Nenhuma mudança é necessária em `backend/agents`: se só chegarem ofertas de restaurantes abertos, o
fluxo dos agentes continua igual. Se o iFood não aceitar `onlyOpen`, registre aqui para combinarmos
outra saída (por exemplo, repassar `is_open` às ofertas e o auditor bloquear).

## Tarefa para Claude / Gabriel — retomada incremental dos agentes (18/10/2026)

**Solicitação explícita do Lorenzo:** corrigir em `backend/agents/**` a continuação
do atendimento para NÃO pesquisar tudo novamente quando mudar somente quantidade
de pessoas ou orçamento. Priorizar esta retomada; não confundir com reenvio HTTP.

### Base já integrada e verificada

- O PR #4 foi mergeado na `main` em `d57d96b`; o commit `27a48da` está no histórico
  da `main`. Ele corrige o dispatch duplicado da MESMA mensagem e configura São Carlos.
- A retomada de mensagens NOVAS relacionadas continua pendente, tanto com memória
  temporária quanto com `SQLiteMemory`. O RAG/SQLite do PR #3 não resolve essa lógica.

### Alteração esperada no módulo dos agentes

1. Em `Orchestrator.handle_message`, carregar os candidatos e sua origem da memória
   do MESMO atendimento, em vez de criar a rodada sempre sem ofertas.
2. Comparar os critérios anteriores com a alteração atual. Se somente quantidade
   ou orçamento mudou e os candidatos continuam válidos, executar planejamento,
   auditoria e demais etapas necessárias usando essas ofertas; não chamar o runtime.
3. Preservar categoria/preferências, localização e restrições não alteradas pelo
   cliente; não apagar a pesquisa anterior nem assumir que uma alteração pequena
   inicia um atendimento novo.
4. Associar assinatura e validade à pesquisa (categoria/consulta, localização,
   filtros, modo/origem e horário). Mudanças relevantes, validade expirada, pedido
   explícito de atualização ou falta de candidatos adequados podem exigir nova busca.
   Não reutilizar dados entre atendimentos/clientes ou entre filtros incompatíveis.
5. Não congelar preços/disponibilidade até o cliente encerrar. Reutilizar a sessão
   OpenCode sozinho não resolve: a decisão de retomar deve acontecer antes da busca.

### Aceite e divisão de trabalho

- **Claude:** implementação e testes de domínio em `backend/agents/**`, usando a
  porta de memória existente; não editar API/integrations nesta tarefa.
- **Codex:** regressões HTTP e revisão da integração. Depois que a correção entrar,
  retirar em coordenação a marca `xfail` do teste de aceite da API e validar novamente.
- Teste existente: `backend/api/tests/test_message_continuity.py::test_related_followup_should_reuse_existing_candidates`.
  Duas variantes (`ephemeral` e `sqlite`), hoje `xfail(strict=True)`: primeiro pedido
  + "Agora são 3 pessoas" devem somar **1 pesquisa total**, não 2.
- Acrescentar aceite equivalente para mudança de orçamento; testar quantidade E
  orçamento alterados em sequência, manutenção das restrições e isolamento de sessões.
- Testar também mudança de categoria/local/filtro e atualização explícita, para
  comprovar que o reaproveitamento não devolve ofertas incompatíveis ou vencidas.
- Todos os testes com `FakeRuntime`/catálogo simulado: **nenhuma chamada Gemini ou iFood**.
- Publicar aqui a resposta do Claude com arquivos alterados, testes e commit/PR.
  **Status (Claude, 18/10): implementado — ver "Resposta do Claude" no topo (PR #7).**

## Novo: módulo de memória implementado (PR #3, `52f0c93`)

**`backend/memory/**` agora é do Claude Code**, por decisão humana (o Codex da memória não tinha
código). **Codex da memória: não reimplemente esta pasta**; proponha mudanças por escrito.

- **RAG mínimo (obrigatório no MVP):** `MarkdownKnowledgeBase` (porta `KnowledgePort` em
  `backend/agents/ports.py`) sobre `backend/memory/knowledge/*.md` — política de desconto e estratégias
  de venda, todos DEMO. Busca por palavras-chave, sem embeddings (PROMPT §6: recuperação simples basta).
  O especialista em descontos usa os números do bloco `params` da política recuperada e cita o
  documento em `knowledge_retrieved`; o estrategista cita a estratégia aprovada. Os agentes ligam a
  base sozinhos em `build_orchestrator` — **a API já tem RAG sem mudar código**.
  Para mudar a política de desconto da demo, edite o documento, não o código.
- **Persistência:** `SQLiteMemory` (porta `MemoryPort`), com a semântica combinada antes: revisão
  atômica, `RevisionConflict` sem gravar, `None` → `null`, cópia independente, auditoria de autor e
  chaves (sem valores). Sobrevive a reinício do processo.
- **Ainda não ligado na API:** ela segue com `backend/api/session_memory.py` (temporária).
  → **Lorenzo:** em `backend/api/main.py`, usar `build_application(memory=SQLiteMemory("<arquivo>.db"))`
  (de `backend.memory`) e garantir que o `.db` não seja versionado.
- Guia: `backend/memory/README.md`. Testes: `python3 -m unittest discover -s backend/memory/tests -t .` (17).

## Teste real em uma segunda máquina (18/10, madrugada)

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
| `backend/memory/**` | Claude Code (antes: Codex da memória) | RAG mínimo + `SQLiteMemory`; a API ainda usa memória temporária |
| Frontend | Equipe de design | Fora deste repositório de backend |

Testes na `main`: `pytest backend/api/tests backend/integrations/tests` (57 aprovados, 1 teste real
opt-in pulado), `python3 -m unittest discover -s backend/agents/tests -t .` (71) e
`python3 -m unittest discover -s backend/memory/tests -t .` (17).

## Como rodar

```bash
# API em modo demo (padrão): catálogo fictício, sem iFood/Gemini/internet
uvicorn backend.api.main:app --port 8000

# API em modo real: exige `opencode serve --hostname 127.0.0.1 --port 4096` rodando na pasta do
# projeto, credenciais locais e OAuth feito (ver backend/api/README.md). Sem as coordenadas abaixo,
# a busca falha com location_required. (No Windows: `set VAR=valor` em linhas separadas.)
APP_RUNTIME_MODE=real IFOOD_SANDBOX_LATITUDE=-22.0175 IFOOD_SANDBOX_LONGITUDE=-47.89083333 \
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
3. **Memória persistente ligada na API** (o `SQLiteMemory` existe; falta a composição em `backend/api/main.py`)
   e **memória do cliente** (preferências e padrões por cliente; hoje o histórico é um exemplo fixo DEMO).
4. **Autenticação real** de comprador e gestor.
5. **Transcrição de áudio** (provedor STT).
6. **Pedidos e pagamento**: desabilitados até haver implementação, permissões e confirmação explícita do cliente.
7. **Interface conectada à API**: ainda não testada com o frontend.

## Próximos passos por responsável

- **Todos:** atualizem sua branch a partir da `main` antes de continuar. Não editem a pasta de outro responsável.
- **Lorenzo (`feat/integrations`):** **prioridade 1: liberar o gestor de demonstração no modo real local** (item 1 do teste acima); depois testar "uma opção vegetariana" ao vivo e a troca futura para Claude no OpenCode. Mudanças entram por novo PR.
- **Lorenzo:** também ligar `SQLiteMemory` na composição da API (ver "módulo de memória" acima).
- **Codex da memória:** a pasta passou para o Claude Code; não duplicar. Revisão do código é bem-vinda.
- **Claude Code (`feat/agents`, `backend/memory`):** memória do cliente (preferências/padrões por cliente),
  economia de chamadas ao runtime (reaproveitar ofertas em mensagens seguintes) e ajustes após testes reais.
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

1. A API mantém o atendimento pelo `session_id` recebido e compõe um orquestrador/memória por aplicação, não por mensagem (`backend/api/services.py`). Correção deste diagnóstico: a idempotência original só evitava repetir o registro da mensagem, mas ainda agendava agentes novamente. Ver a correção e os testes no relatório de memória/São Carlos abaixo.
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

## Relatório Codex / Lorenzo — memória, reenvios e São Carlos — 18/10/2026

### Base revisada e resultado sobre a memória

- Revisada `origin/main@9dd9acf`, incluindo o merge do PR #3, os recados acima, composição da API, orquestrador/pesquisador, runtime, `SQLiteMemory` e recuperação RAG. Os módulos de agentes/memória vieram por merge; não foram editados pelo Codex.
- **SQLite e RAG NÃO corrigiram a retomada do atendimento.** `build_application()` ainda usa `EphemeralSessionMemory` por padrão. A persistência pode ser injetada, mas o orquestrador continua criando `WorkingState` sem candidatos a cada mensagem.
- Reprodução com `SQLiteMemory(":memory:")` injetada: primeira mensagem fez 1 chamada e gravou 3 candidatos; "Pode ser mais barato?" fez mais 1 chamada, apesar dos mesmos candidatos salvos. Trocar o armazenamento não muda a decisão de pesquisar.
- Persistir `MemoryPort` não persiste automaticamente o cadastro/autorização das sessões HTTP, as projeções e o histórico SSE, nem a idempotência HTTP. Não anunciar retomada após reiniciar a API somente por ligar o SQLite.

### Codex — correção integrada à `main` pelo PR #4 (`d57d96b`)

- Corrigido disparo duplo no reenvio da MESMA mensagem: `accept_message_once` decide atomicamente, sob o lock do estado, se o envio é novo. O endpoint só agenda a execução para o primeiro aceite. Nenhum DTO ou endpoint público foi alterado.
- Testado com memória efêmera e SQLite: reenvio sequencial, 5 reenvios simultâneos, ID igual com conteúdo diferente (`409`), mesmo ID em outra sessão (independente), falha de runtime sem repetição automática e nova tentativa explícita com ID novo.
- Isso NÃO é cache de ofertas e NÃO corrige o caso de mensagens novas relacionadas. A garantia HTTP ainda é por processo, não durável entre reinícios.

### Localidade atual: São Carlos/SP, não São Paulo capital

- Referência pública aproximada: latitude **-22.0175**, longitude **-47.89083333** (GeoNames: https://www.geonames.org/advanced-search.html?country=BR&q=Sao+Carlos).
- Novo preset opt-in `IFOOD_TEST_LOCATION=sao_carlos`, sempre marcado `public_test`. Não é sandbox oficial nem endereço residencial/entrega do comprador.
- Novo launcher: `python -m backend.api.run_local --real`, vinculado a `127.0.0.1`; limpa coordenadas antigas herdadas SOMENTE no processo e seleciona São Carlos. Sem `--real`, inicia em demo. Não altera variáveis permanentes do PC.
- Uso normal via uvicorn continua sem fallback implícito: configurar preset ou coordenadas explicitamente. Coordenadas do contexto do runtime têm prioridade; texto de cidade não é geocodificado.
- Corrigidos exemplos no README e neste documento e scripts locais de próximas buscas; as evidências/fixtures históricas de buscas em São Paulo foram preservadas, não rebatizadas.
- Servidor já iniciado não muda de cidade sozinho: reiniciar usando o launcher. Nenhuma chamada real foi feita para confirmar disponibilidade/cobertura de São Carlos.

### Claude — encaminhamento de continuidade

- Corrigir em `backend/agents`: recuperar candidatos válidos do mesmo atendimento antes de ativar pesquisador e comparar o que mudou. Quantidade/orçamento devem tentar replanejar antes de pesquisar de novo.
- Registrar assinatura e validade da busca (categoria/consulta, local, filtros, modo/origem), com invalidação quando necessário e atualização explícita. Não misturar consultas com filtros diferentes, nem sessões/clientes.
- Há aceite HTTP offline em `backend/api/tests/test_message_continuity.py::test_related_followup_should_reuse_existing_candidates`, em duas variantes de memória, marcado `xfail(strict=True)` porque o defeito dos agentes permanece. Depois da correção, retirar a marca em coordenação com o Codex. O teste novo deve ter 1 chamada total para primeira mensagem + alteração de quantidade; hoje tem 2.
- O RAG é conhecimento comercial, não cache do catálogo iFood. Não usar a presença do RAG como evidência de reutilização de ofertas.
- Encerramento explícito, seleção/explicação de propostas e atualização parcial de restrições precisam de testes adicionais. Nenhum novo endpoint de encerramento foi inventado nesta revisão.

### Verificação desta entrega

- Suíte completa offline: **160 aprovados, 1 teste real opt-in pulado e 2 falhas esperadas (`xfail`) de continuidade**, uma com cada memória. Sem Gemini/iFood, sem pedidos/pagamentos.
- Testes de localização conferem as coordenadas enviadas no prompt ao OpenCode simulado, precedência de localização explícita, ausência de fallback não solicitado, preset inválido e substituição de São Paulo no launcher.
- Lint dos arquivos Python alterados: aprovado. Não foram ligadas automaticamente persistência SQLite na API nem a opção de gestor em modo real; continuam pendentes.
- Atualização de publicação: código e relatório desta entrega entraram na `main` pelo PR #4, merge `d57d96b`, com autorização do Lorenzo. A pendência de publicação descrita anteriormente foi resolvida. A retomada dos agentes NÃO foi implementada nesse PR; ver tarefa explícita no topo deste arquivo.
