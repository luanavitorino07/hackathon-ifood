# Atualização do projeto — 18/10/2026

## MAIS RECENTE — Compras de supermercado (na hora ou agendadas) — PR #18 (18/10/2026, `main@8508b4c`)

**Na main e rodando na API 8000.** Arquitetura completa para o documento final: `docs/ARQUITETURA_AGENTES.md`.

- Cliente pode mandar lista de mercado: "compra do mês no mercado: arroz 5kg, 2 feijões, leite e café" ou
  agendar: "mercado todo sábado às 10h: ...". "adiciona café", "tira o leite", "meus agendamentos" e
  "cancelar agendamento" funcionam.
- **Agente novo: Montador da cesta (IA)** — escolhe produto e quantidade por mercado; Auditor confere.
  Catálogo agora tem **10 agentes**. O agendamento é regra do orquestrador (não é agente).
- Agendamento fica pendente até o cliente confirmar; na data a API (relógio a cada 30 s,
  `APP_SCHEDULE_TICK_SECONDS`, `0` desliga) refaz a cesta com os preços do dia e pede confirmação.
  **Nunca compra sozinho**: o MCP liberado só busca. Agendamentos ficam na memória da API (reiniciar apaga).
- **Lorenzo:** com autorização do Gabriel, o Claude alterou `backend/integrations/agent_runtime.py`
  (`merchant_type`/`merchant_id` do contexto vão para o `searchOffers`, com validação) e `backend/api`
  (`ScheduleTicker`, `run_due_schedules`). Os 2 testes antigos foram ajustados (10 agentes; permissões sem
  índice). Suítes: agentes 170, memória 19, API+integrações 153 ok.
- Testado no iFood real + Haiku: "lista do mercado: arroz 5kg e café" → cesta no Oba Hortifruti São Carlos.
- **PR #22:** **custo de IA por cliente** na Análise financeira (tokens, custo US$/R$, vendido, % da venda e
  lucro estimado). Custo vem do OpenCode; câmbio (`APP_USD_BRL_RATE`) e margem DEMO são parâmetros.
  **Contrato:** novo `GET /api/v1/admin/ai-usage` (gestor) e `overview.estimated_ai_cost_cents` preenchido.
- **PR #20:** comida com bebida + acompanhamento ("parmegiana com coca e batata frita") saía só com um. Agora o
  Pesquisador procura o complemento dentro do restaurante do prato e a opção completa vem primeiro. Testado no real.
- **PR #19 (correção):** "adiciona detergente" deixava a cesta só com arroz (IA julgava só parte de 100
  produtos). Agora vão no máximo 6 candidatos por item e o não julgado usa a regra por palavras. Testado no real.

## PASSAGEM PARA OUTRA CONTA / SESSÃO — leia primeiro (18/10/2026, `main@b499d4b`)

Gabriel vai continuar o trabalho em outra conta do Claude. Este bloco é o estado completo agora.

### Onde está o código
- **Tudo na `main`**: PR #15 (Intérprete, agentes conversando, conflitos, memória/clientes fictícios),
  PR #16 (interface nova + Análise financeira), PR #17 (complementos na busca, restrições pela IA, menos avisos).
- Pastas locais: `/home/bagiel/hackaton/hackathon-ifood` = checkout da **main** (serve a 8080);
  `/home/bagiel/hackaton/hack-agents` = worktree do Claude (branches `feat/agents`, `feat/frontend-ceo`,
  `teste/web` local de teste — pode apagar).
- Testes: agentes+memória **151 ok** (`python -m unittest discover -s backend/agents/tests -t .` e
  `... -s backend/memory/tests`); frontend `npx tsc --noEmit` + `npm test` (7 ok). API/integrações:
  147 ok e **2 falham por suposição antiga** (ver “Lorenzo: 2 testes” abaixo; ajuste de 1 linha cada).

### O que está rodando nesta máquina (abrir **http://localhost:8080**)
| Porta | O quê | Como subir de novo |
|---|---|---|
| 4096 | `opencode serve` (na pasta da main) | `opencode serve --hostname 127.0.0.1 --port 4096` |
| 8000 | API, **Claude Haiku + Whisper**, modo real | comando abaixo (pasta da main) |
| 8081 | Expo web (sem `CI=1`, senão não recarrega) | `cd frontend && EXPO_PUBLIC_USE_MOCKS=false EXPO_PUBLIC_DEMO_ADMIN=true npx expo start --web --port 8081 --clear` |
| 8080 | proxy (frontend + `/api`) | `cd frontend && npm run proxy` |

```
APP_STT_PROVIDER=whisper APP_STT_MODEL=small OPENCODE_BASE_URL=http://127.0.0.1:4096 \
OPENCODE_PROVIDER_ID=anthropic OPENCODE_MODEL_ID=claude-haiku-5-5 OPENCODE_MODEL_VARIANT= \
python -m backend.api.run_local --real --port 8000 --local-demo-admin --include-closed-restaurants
```
- O Python usado tem faster-whisper/ffmpeg: venv em
  `/tmp/claude-1000/-home-bagiel-hackaton-hack-agents/14e4b907-66eb-498d-9142-2463ba91ab31/scratchpad/venv`
  (em `/tmp`: some se a máquina reiniciar; aí recriar com `requirements` + `backend/integrations/requirements-stt.txt`).
- **API 8000, Expo 8081 e OpenCode 4096 foram iniciados pela sessão anterior do Claude**: se pararem
  ao trocar de conta, subir de novo com os comandos acima. Uma API antiga na porta **8002** pode ser encerrada.
- Memória da API é do processo: reiniciar apaga o histórico de teste; os 4 clientes fictícios voltam sozinhos.
- Chaves: Anthropic e Google cadastradas no OpenCode (`opencode auth list`). **Nunca colar chave no chat.**
  Chave Anthropic precisa ser de **workspace** (chave de organização dá 400). iFood OAuth em
  `backend/integrations/.local/` (gitignored). Para voltar ao Gemini: subir a API sem as 3 variáveis `OPENCODE_*`.

### Como o bot funciona agora (resumo)
Intérprete (IA) entende prato, complementos ('com coca'), pessoas, orçamento, restrições (inclusive de parte
do grupo), preferências, confirmação ('fechado' registra venda) e correções ('não sou vegano'). Pesquisador
busca no iFood (prato + 1 busca por complemento). Curador (IA) julga prato, porções, restrições (dieta só com
confirmação; saúde quando não há violação) e pede nova busca se nada serve. Planejador/Auditor por regra.
Estrategista (IA) escolhe estratégia nomeada consultando a Memória; Descontos (IA) só sugere ao gestor.
Conflitos reais: Curador×Pesquisador, Orçamento×pedido, Estrategista×Descontos, Pedido×cadastro, Planejador×Auditor.
Detalhes: `backend/agents/README.md`.

### Pendências conhecidas
1. **Lorenzo**: `test_acceptance.py:124` (8→9 agentes) e `test_real_search_quality.py:426` (índice das permissões).
2. Complemento (coca) quase nunca vem do mesmo restaurante: a busca `searchOffers` não filtra por loja;
   o bot diz “peça à parte” ou escolhe combo com bebida. Não inventar ferramenta.
3. Na apresentação em horário comercial, tirar `--include-closed-restaurants`.
4. Haiku: ~10–30 s por pedido, 5–7 chamadas de IA por pedido (centavos); acompanhar saldo da Anthropic.
5. Regras: não commitar segredos; não editar `AGENTS.md`; módulos de outros donos (backend/api,
   backend/integrations = Lorenzo) só com autorização do Gabriel; merge na main só com autorização;
   recados ao time vão neste arquivo, na main, com push.

## MAIS RECENTE — Claude: agentes com mais IA, interface nova e Claude Haiku (18/10/2026)

**Status: NA MAIN** (PRs #15, #16 e #17 mergeados). Gabriel autorizou o Claude a mexer também no frontend.
- **PR #15 (`feat/agents`)**: agentes + memória. **PR #16 (`feat/frontend-ceo`)**: frontend.
- Testado ao vivo com iFood real + **Claude Haiku** (`anthropic/claude-haiku-5-5`): ~10–30 s por
  pedido (Gemini levava ~110 s). Sem erros no console do navegador.

### O que muda para quem usa
- **Intérprete (agente novo, IA)** entende o pedido com o contexto: "eu e 3 amigos, um é vegano, poke"
  → 4 pessoas + opção vegana; "intelorancia a lactose, quero sorvete" → busca "sorvete" + sem lactose;
  "acha um montado" → poke já montado; "fechado/pode ser" → venda registrada.
- **Curador** avalia restrições pelo nome do item (com aviso "avaliada pela IA, confirme com o
  restaurante") e, se nada serve, **pede outra busca ao Pesquisador**.
- **Agentes conversam entre si** (não só com o orquestrador) e há **conflitos reais**: Curador ×
  Pesquisador, Orçamento × pedido (fica aberto até o cliente responder), Estrategista × Descontos,
  Pedido × cadastro, Planejador × Auditor.
- **Descontos** agora atuam também no modo real (só sugestão ao gestor; hipóteses DEMO).
- **Clientes fictícios** (Ana, Bruno, Carla, Diego) com histórico e cadastro, escolhidos no chat;
  memória em `backend/memory/demo_seed.py` (desligar: `APP_DEMO_CUSTOMERS=0`).
- **Análise financeira** (ex-"Visão do CEO"): indicadores + **monitoria de estratégias** (qual vende).
- Chat: recomendações antigas não somem mais; cabeçalho e cards novos.

### Lorenzo: 2 testes da API supõem o comportamento antigo (ajuste de 1 linha cada)
- `backend/api/tests/test_acceptance.py:124` — `len(agents) == 8` → agora **9** (entrou o Intérprete).
- `backend/api/tests/test_real_search_quality.py:426` — `permissions[1]` supõe que a 1ª chamada é a
  busca; agora a 1ª é o raciocínio do Intérprete. Sugestão: procurar a lista de permissões com
  `StructuredOutput` em vez de usar o índice. Demais 147 testes da API/integrações passam.

### Subir a API com Claude Haiku + áudio (comando da apresentação)
Chave da Anthropic cadastrada no OpenCode (`opencode auth login` → Anthropic, chave de **workspace**;
chave de organização dá erro 400). Reiniciar o `opencode serve` depois de cadastrar.
```
APP_STT_PROVIDER=whisper APP_STT_MODEL=small \
OPENCODE_PROVIDER_ID=anthropic OPENCODE_MODEL_ID=claude-haiku-5-5 OPENCODE_MODEL_VARIANT= \
python -m backend.api.run_local --real --local-demo-admin --include-closed-restaurants
```
`OPENCODE_MODEL_VARIANT=` vazio é obrigatório (o padrão `low` é do Gemini). Sem `APP_STT_PROVIDER`
o botão de áudio responde "transcrição não configurada". Na apresentação em horário comercial,
tirar `--include-closed-restaurants`.

## INTEGRAÇÃO MAIS RECENTE — frontend + áudio + main (18/10/2026)

**Este bloco substitui o estado anterior de “frontend não integrado” e “áudio só local”.**
Gabriel autorizou integrar `origin/front-end@87a429c`, `feat/audio-stt@d998d79` e o backend
atual à main, preservando o design. Integração preparada na branch `integration/frontend-audio`.

**Publicação concluída:** merge **`2337f00`** na `origin/main`, incluindo frontend e áudio.
API 8000, Expo 8081 e proxy 8080 reiniciados a partir do checkout principal da main;
OpenCode principal continua em 4096. Conferência final pelo proxy: HTML e bundle 200,
overview do gestor 200, 8 agentes, comprador sem acesso ao catálogo administrativo,
criação de sessão 201 em modo real e STT ativo rejeitando arquivo inválido com 422.
Os processos temporários de teste não são o destino do proxy em 8080.

### O que a entrega integra

- Interface Expo/React Native recebida da equipe: chatbot, dashboard, painel dos agentes
  e conflitos. API real é o padrão; simulação exige `EXPO_PUBLIC_USE_MOCKS=true`.
- Proxy same-origin em **http://localhost:8080** → frontend 8081 / API 8000. API usa
  OpenCode 4096 e Gemini/iFood reais. Executar o frontend por 8080, não 8081.
- Microfone do navegador e seletor de arquivo → Whisper small local → texto editável →
  confirmação/envio. O frontend preenche `input_mode` e `transcription_id`, sem copiar JSON.
  Áudio não usa Gemini; a recomendação posterior usa o fluxo de agentes normal.
- Memória operacional, `initial_context` opcional pela API, recomendações, mensagens,
  histórico, eventos SSE, decisões, consultas RAG/memória, conflitos e métricas conectados.
  Não foi criado formulário visual de perfil nem inventada integração de identidade iFood.
- Sessão recuperada na mesma aba após refresh; ID perdido por reinício da API abre nova
  sessão. Botão “Novo atendimento”; indicador de processamento/transcrição e reenvio
  idempotente. Snapshot atualizado também durante recuperação de histórico.
- Corrigido conflito entre o cookie administrativo e o chatbot no mesmo navegador:
  comprador envia `X-Demo-Role: customer`, inclusive no SSE, e não herda papel de gestor.
  Gestor local exige `--local-demo-admin`; isso continua sendo autenticação de demo local.
- Tipos TS alinhados aos metadados atuais de recomendações. Loja fechada tem aviso e não
  permite revisar/submeter pedido. Revisão de loja disponível informa que envio real ainda
  não está implementado; botão real desabilitado. Nenhum checkout/pagamento foi inventado.
- Arquivos `.pyc` acidentais da branch frontend foram retirados do índice; caches locais
  preservados, com `.gitignore` para não voltarem aos commits.

### Verificação realizada nesta integração

- **289 testes Python passaram, 3 opt-in reais ignorados na suíte offline**; smoke test
  de fixtures/contrato frontend-backend passou; TypeScript sem erros; 4 testes TS passaram;
  `expo export --platform web` gerou bundle/HTML/fontes com sucesso.
- Teste separado **HTTP real pelo proxy da interface (8080)**: catálogo de 8 agentes,
  cookie gestor, comprador sem permissão administrativa, áudio de fala sintética em
  português transcrito pelo Whisper real, sessão e mensagem com `input_mode: audio`.
  Texto revisado no teste acrescentou orçamento de R$ 1000 antes de enviar.
- Busca iFood real incluindo lojas fechadas → Curador, Planejador, Auditor, consulta de
  memória/RAG, Estrategista e resposta do Orquestrador. **44,3 segundos do envio à resposta**,
  uma recomendação `ifood_mcp`, nenhuma ocorrência de erro e eventos de sucesso de IA para
  `curator`, `sales_strategist` e `orchestrator`. Quatro chamadas esperadas ao modelo no fluxo;
  não repetimos a busca para testar reenvio.
- Resultado: opção alternativa Combo 2 Pizzas da Just Pizza, R$ 98,99; a resposta informou
  correspondência parcial, loja fechada/somente teste e taxa de serviço não incluída.
  Isso valida transporte/colaboração, não acerto semântico universal ou disponibilidade real.
- **SSE real pelo proxy:** comprador recebeu 4 eventos, gestor 36; nenhum `visibility: admin`
  no stream do comprador, comunicações `agent_message` presentes no gestor. Reenvio do mesmo
  ID não duplicou mensagem; recuperação de histórico respeitou `after_seq`.
- Não houve automação visual de navegador: ferramenta de navegador não estava disponível.
  HTML/bundle, HTTP, SSE e transcrição foram testados; aparência final, permissão real do
  microfone e interação humana no navegador precisam de conferência da equipe.

### Rodar / limites para o pitch

Ver `frontend/README.md` e `backend/integrations/AUDIO.md`. No ambiente Python com as
dependências de áudio e ffmpeg instalados, iniciar OpenCode na raiz do projeto e a API:

```sh
opencode serve --hostname 127.0.0.1 --port 4096
# Em outro terminal, com o ambiente Python correto ativado:
APP_STT_PROVIDER=whisper APP_STT_MODEL=small python -m backend.api.run_local --real --local-demo-admin --include-closed-restaurants
# Em outros dois terminais, dentro de frontend/:
npm ci
npm run web
npm run proxy
```

O flag de lojas fechadas é somente para o ensaio fora de horário; removê-lo para pesquisar
apenas lojas abertas. Nunca implica autorização para compra. Não iniciar duplicatas nas
mesmas portas se os serviços já estiverem rodando. A cota Gemini continua limitada.

RAG comercial permanece DEMO; memória de cliente entre reinícios foi adiada por Gabriel;
autenticação de produção e envio real de pedido/pagamento seguem pendentes. A documentação
antiga de `feat/memory` ainda precisa ser reconciliada; não mesclar suas versões antigas de
schemas sobre os atuais. O restante deste arquivo é histórico do trabalho anterior.

## ESTADO ATUAL — leia esta seção antes de qualquer relatório histórico

> Fotografia anterior à integração do frontend. Para o estado vigente, usar o bloco acima.

**Atualizado pelo Codex local a pedido de Gabriel. Este bloco substitui diagnósticos,
prioridades e pendências antigas que conflitem com ele. O histórico abaixo foi mantido
para rastreabilidade, não como lista de tarefas atuais.**

### Lorenzo / Codex: o bloqueio antigo da “pizza da esfiharia” foi corrigido

O diagnóstico de `e2f03b6` dizia que o Curador não conseguia chamar a IA e caía no
filtro lexical, deixando passar “Pizza” de R$ 8,99 da esfiharia e “Pastel de Pizza”.
**Não tratar esse diagnóstico como estado da main atual.**

- Correção do runtime: **`8acbc27`**, feita pelo Codex/Lorenzo.
- Merge na main autorizado por Gabriel: **`d77049a`**.
- Registro da validação completa na main: **`9b4a329`**.
- StructuredOutput está habilitado como ferramenta interna; resposta lida de
  `info.structured`; raciocínio não faz o GET de histórico incompatível.
- OpenCode usa os agentes enxutos `ifood-search` e `ifood-reasoning`.
- Teste real de regressão do Lorenzo, com catálogo sintético: Curador rejeitou pastel,
  esfiha sabor pizza e “Pizza” barata de esfiharia. Essa evidência é do relatório dele.
- Teste independente do Codex local **com catálogo iFood real** chegou à recomendação
  final com Curador, Estrategista e Orquestrador usando Gemini de verdade.

**Limite da conclusão:** o defeito de integração que desativava a IA foi corrigido e
o fluxo real passou. Isso não prova acerto semântico para todo item. Se o modelo falhar
por cota/timeout, ainda existe fallback por regras. Se houver nova “pizza da esfiharia”,
registrar a versão, a sessão nova e o evento `raciocinio_ia` do Curador (`succeeded` ou
`failed`) antes de concluir que é o mesmo bug. Não reaproveitar sessão/resultado antigo
para validar correção; há reutilização de busca e julgamento por até cinco minutos.

### O que foi comprovado no fluxo real

Em 18/10, pedido **“Quero pizza para 1 pessoa até R$ 1000”**, coordenadas públicas de
São Carlos, lojas fechadas incluídas explicitamente para teste:

1. Pesquisador consultou MCP iFood: **6 ofertas de 2 restaurantes**.
2. Curador chamou Gemini: **4 itens aprovados, 1 parcial, 1 rejeitado**.
3. Planejador montou **2 propostas por regras**; Auditor aprovou **2 por regras**.
4. Estrategista consultou Memória do Cliente (sem histórico naquele atendimento) e
   RAG; chamou Gemini para ordenar as propostas e devolveu a decisão ao Orquestrador.
5. Orquestrador chamou Gemini e entregou resposta ao consumidor.

**29,2 segundos, 4 chamadas ao modelo, script de verificação com exit code 0.**
Recomendações: Marguerita da Just Pizza **R$ 60,99** e Quatro Queijos **R$ 70,99**,
com `data_origin: ifood_mcp`, `is_open: false`, aviso explícito de loja fechada e
indisponível para pedido e taxa de serviço desconhecida não incluída. Nenhuma compra.
Houve eventos reais de comunicação entre os agentes e de sucesso das três análises de IA.

Este teste usou API via ASGI com runtime/modelo/MCP reais; não foi teste da interface
nem do SSE no navegador. O documento comercial do RAG continua **DEMO**. A busca anterior
somente em lojas abertas retornou zero ofertas; outra para duas pessoas até R$ 150
não gerou combinação válida. Não confundir esses resultados com falha de StructuredOutput.

### Versões e processos locais de Gabriel — conferidos nesta atualização

| Componente | Estado atual |
| --- | --- |
| Main remota | Contém a integração `d77049a` e o registro `9b4a329`; este documento acrescenta atualização posterior |
| OpenCode principal | Reiniciado após o merge; `127.0.0.1:4096`, versão 1.19.3, health OK, iFood conectado, agentes `ifood-search` e `ifood-reasoning` carregados |
| API principal local | `127.0.0.1:8000`, modo real; foi reiniciada com main atualizada e depois com a branch de áudio descrita abaixo |
| Código servido atualmente pela API | Worktree `/tmp/ifood-audio-stt`, branch **`feat/audio-stt`**, commit **`d998d79`**, baseada em `9b4a329` |
| Áudio no GitHub | **Ainda não publicado nem mergeado**; commit existe localmente. Dar pull na main não instala áudio |
| OpenCode temporário | Porta 4097 foi usada nos testes; a API atual aponta para **4096**, não para esse serviço temporário |

Na máquina do colega, atualizar o código e reiniciar os próprios processos continua
necessário: o reinício feito em Gabriel não atualiza outro computador. Antes de novo
teste, conferir `git log -1`, se `8acbc27` é ancestral do checkout, e se `/agent` do
OpenCode lista ambos os agentes acima. `connected` sozinho não substitui uma busca real.
O modelo usado nos testes foi `google/gemini-3.8-flash`; não foi trocado para Claude.

### Áudio: implementado e ativo localmente, separado da main

- Branch local `feat/audio-stt`, commit `d998d79`; arquivos: `backend/api/app.py`,
  `backend/api/main.py`, `backend/integrations/local_transcription.py`,
  `backend/integrations/requirements-stt.txt`, `backend/integrations/AUDIO.md` e
  `backend/integrations/tests/test_local_transcription.py`.
- Whisper `small` em CPU, `APP_STT_PROVIDER=whisper`, `APP_STT_MODEL=small`, ffmpeg e
  faster-whisper instalados no ambiente local da API. Sem chave ou cota Gemini para STT.
- **HTTP real na porta 8000**, WebM/Opus com fala sintética em português: transcreveu
  “Eu quero uma pizza. Sem cebola. Para uma pessoa.” corretamente em **6,8 segundos**.
  Teste ASGI com WAV: 14,43 segundos; silêncio retornou 422 `STT_NO_SPEECH`.
- Contrato preservado: `POST /api/v1/audio/transcriptions` retorna texto,
  `transcription_id`, `language: pt-BR` e `requires_confirmation: true`. A interface
  revisa e envia pelo chat com `input_mode: audio`; transcrição não dispara agentes.
- Limites: 10 MiB/120 segundos; áudio não é gravado em arquivo. Ainda falta gravação
  humana pelo microfone e integração do frontend. Voz sintética não valida todo sotaque/ruído.
- Suíte da main integrada: **283 passed, 3 skipped**. Suíte com áudio: **288 passed,
  3 skipped**. Testes opt-in reais foram executados separadamente, não estão incluídos
  como chamadas reais na contagem offline. Nenhuma nova chamada Gemini nesta atualização.

### Memória, interface e pendências que realmente continuam

- **Memória operacional:** SQLite em arquivo já é o padrão da API; não pedir novamente
  para “ligar SQLite”. Isso não persiste o cadastro HTTP, eventos SSE e idempotência.
- **Memória do cliente:** ligada ao Estrategista; dados por cliente/tenant durante o
  processo. São solicitações ao bot, não compras confirmadas. Persistência entre reinícios
  **adiada explicitamente por Gabriel**: o pitch terá uma execução contínua.
- **RAG:** ligado, documentos comerciais DEMO; não representa margens/descontos reais.
- **Frontend:** equipe está terminando a interface; integração visual e reconexão SSE
  com o frontend final ainda pendentes. Não alterar design/frontend por causa deste relato.
- **Gestor local:** suporte/cookie já existe na main; iniciar com `--local-demo-admin`
  para habilitar no modo real. A API atual foi iniciada com `--real`, sem esse flag.
  Para testar lojas fechadas, opção `--include-closed-restaurants` (não habilitada por
  padrão). Esses flags são de demonstração local, não autenticação de produção.
- **Contrato:** API já aceita `initial_context`; os documentos antigos em `feat/memory`
  ainda precisam ser conciliados com os campos mais recentes de `PROMPT.md`/modelos.
  Essa reconciliação não foi feita e não bloqueia o teste local já descrito.
- **Compra:** carrinho/envio real de pedido, checkout, pagamento e desconto real não
  foram entregues/validados por este trabalho. Exigem ferramentas autorizadas e confirmação.
- Próximo trabalho: integrar a interface; revisar/publicar a branch de áudio antes de
  outra máquina tentar usá-la; testar microfone e continuidade no cenário do pitch.
  Não repetir buscas pagas apenas para reproduzir evidência já registrada.

## HISTÓRICO — diagnósticos e prioridades abaixo não descrevem o estado atual

<details>
<summary>Relatórios anteriores preservados: ler pela versão citada, não como pendência atual</summary>

> Leia antes de continuar. A correção de `feat/integrations@8acbc27` foi integrada
> à `main` com autorização explícita de Gabriel em 18/10/2026. As regras de trabalho
> continuam em `AGENTS.md`; o produto e o contrato em `PROMPT.md`.
> As seções anteriores foram preservadas abaixo como histórico; os bloqueios antigos
> de StructuredOutput foram resolvidos conforme a validação abaixo.

## Integração autorizada e teste real concluído — Codex local (18/10/2026)

Integrada a branch `feat/integrations` até `8acbc27`, preservando os agentes e a memória
já presentes na main. Inclui correção de StructuredOutput, agentes OpenCode com prompts
menores, tratamento de cota, SQLite operacional padrão, gestor local com cookie,
metadados de recomendações e opção explícita de teste com restaurantes fechados.
Nenhuma edição de frontend ou design.

### Evidência real (antes do merge, mesma versão de código)

- API executada em processo de teste por transporte ASGI; OpenCode 1.19.3 local,
  Gemini `google/gemini-3.8-flash` e MCP iFood reais, sem substituir respostas por mocks.
- Pedido: “Quero pizza para 1 pessoa até R$ 1000”. Coordenadas públicas de São Carlos;
  inclusão de lojas fechadas habilitada somente para teste, sem representar endereço do cliente.
- Fluxo concluído em **29,2 segundos**, com quatro chamadas ao modelo: pesquisador,
  Curador, Estrategista e resposta do Orquestrador. Script terminou com código zero.
- Pesquisador: seis ofertas reais de dois restaurantes. Curador: quatro itens aprovados,
  um parcial e um rejeitado. Planejador: duas propostas. Auditor: duas aprovadas.
  Planejador e Auditor executaram regras determinísticas, não chamadas adicionais de IA.
- Estrategista consultou a memória (cliente sem histórico/preferências) e o RAG, escolheu
  a ordem por IA e devolveu sua decisão ao Orquestrador. Eventos `agent_message` e
  `tool_activity` confirmaram as interações e as três análises de IA bem-sucedidas.
- Resposta final: Marguerita da Just Pizza, item R$ 50,00 + entrega R$ 10,99 = R$ 60,99;
  segunda opção Quatro Queijos, R$ 70,99. Ambas com `data_origin: ifood_mcp` e `is_open: false`.
  Resposta e recomendações avisaram que a loja estava fechada e indisponível para pedido;
  taxa de serviço desconhecida não incluída no valor apresentado.
- Tentativas anteriores: busca somente em lojas abertas retornou zero ofertas; busca
  para duas pessoas até R$ 150 chegou ao Curador, mas não gerou combinação válida.
  Esses resultados não foram apresentados como validação completa.

### Limites e próximos passos

- Catálogo e IA foram reais; o documento comercial recuperado pelo RAG continua
  identificado como **DEMO**. Descontos reais, áudio, checkout e pagamento não foram
  validados nesta rodada. Nenhum pedido, carrinho ou pagamento foi executado.
- O teste validou endpoints ASGI, projeções e eventos internos; não foi uma validação
  do frontend nem da transmissão SSE por conexão de navegador.
- Merge de código não reinicia processos: reiniciar a API e o OpenCode da aplicação
  para carregar os novos agentes `ifood-search` e `ifood-reasoning` de `opencode.json`.
  O runtime temporário usado no teste não substitui automaticamente o servidor principal.
- Os novos campos públicos estão documentados em `PROMPT.md` e nos modelos da API.
  A documentação de `feat/memory` (`7c41360`, `61b2c44`) não foi mesclada nesta operação:
  `docs/CONTRATO_INTERFACE.md` precisa ser reconciliado com esses campos antes de integrar
  aquela branch. O contexto inicial já existe na API, mas sua descrição também precisa
  ser reconciliada no contrato principal. Não usar a documentação antiga como contrato completo atual.
- Autenticação local de demonstração não equivale a autenticação de produção. SQLite
  operacional não torna persistentes as sessões HTTP, eventos SSE e idempotência da API.

Validação offline repetida sobre a **main integrada**: **283 testes passaram, 3 testes
ao vivo opt-in ignorados**, em 4,54 segundos. `git diff --check` sem erros.
Nenhuma chamada adicional de IA foi feita para essa conferência.

## Correção Codex / Lorenzo — StructuredOutput e consumo de tokens (18/10/2026)

Revisada a nova `origin/main@16f7d82`; relatório incorporado à `feat/integrations`.
As três incompatibilidades reportadas pelo Claude foram corrigidas:

- Raciocínio libera **somente `StructuredOutput`**, tanto nas tools quanto na permissão da sessão;
  MCP e demais ferramentas continuam negados para os especialistas.
- Cliente lê `info.structured`, aceita o nome antigo `structured_output` e usa como reserva apenas
  uma tool `StructuredOutput` concluída com `metadata.valid=true`.
- Sessões com JSON Schema usam o corpo do POST; nenhum GET de histórico dessas sessões.

`opencode.json` agora configura `ifood-search` e `ifood-reasoning`, com prompts de 152 e 151 caracteres.
O runtime os seleciona explicitamente, em vez do `build`; o prompt adicional da busca também foi
encurtado. Não foram removidos os especialistas nem seus guarda-corpos, nem alterado o modelo.
O agente de busca usa três passos: em dois, OpenCode 1.19.3 injeta `MAX_STEPS_PROMPT` como uma mensagem
de assistente **antes da resposta final da busca**, e o Gemini rejeita com HTTP 400
`Requests ending with a model turn are not supported`. O raciocínio estruturado termina no primeiro
passo e mantém limite de dois. Recarregar/reiniciar OpenCode e reiniciar a API ao atualizar.

Validação concluída:

- **283 testes offline aprovados**, 3 testes ao vivo opt-in ignorados na execução offline; lint dos
  arquivos alterados aprovado. O teste HTTP agora usa também o cliente OpenCode real com transporte
  simulado, cobrindo o formato correto, permissões e ausência de GET no raciocínio.
- **Curador no OpenCode 1.19.3/Gemini real**, com itens sintéticos: aceita pizza grande e rejeita pastel
  de pizza, esfiha sabor pizza e "Pizza" de R$ 8,99 da esfiharia. Uma chamada, sem busca iFood:
  **1.708 tokens de entrada + 157 de saída = 1.865**, versus ~8.400 reportados no teste anterior.
  As entradas diferem; não é um percentual garantido por pedido.

A validação completa com catálogo teve uma tentativa sem resposta do modelo (timeout), depois uma
busca MCP real com **13 resultados**, interrompida no passo final pelo erro HTTP 400 descrito acima.
Após ajustar os passos, a continuação foi bloqueada pela **cota diária confirmada do Gemini**:
`generate_content_free_tier_requests`, limite 20, espera informada de ~17h. Portanto **não foi
confirmado um novo fluxo completo com catálogo + Curador + recomendação** nesta entrega.

Corrigido também o tratamento dessa condição: enquanto o POST está pendente, o cliente consulta
somente o status local da sessão a cada dois segundos. Ao detectar retry por cota, aborta a sessão e
normaliza como `quota`, sem expor a mensagem privada do provedor. O runtime faz cooldown de 30 s para
evitar novas chamadas dos especialistas seguintes. Teste real na cota esgotada: erro em **2,52 s**;
segunda chamada negada localmente em **0,016 s**, em vez de novas tentativas e timeout de 40–60 s.

Nenhuma edição em `backend/agents` ou `backend/memory`. Nenhum carrinho/pedido/pagamento executado.
Código segue na branch de integrações; este registro não significa merge de código na `main`.

## 🔴 Revisão do Claude em `feat/integrations@e2f03b6` — IA dos agentes NÃO roda no modo real (18/10/2026)

**Aprovado nesta entrega:** raciocínio sem ferramentas (`_execute_reasoning`), filtro por nome removido
(Curador decide), teste 6→8 agentes, gestor local + cookie (re-testado: SSE do gestor só com cookie = 36
eventos, 12 `agent_message`), detalhes de entrega. Suíte: **134 passed, 1 skipped**; agentes/memória OK;
aceite 6/6. Sem segredos; nada em `backend/agents`/`backend/memory`.

**Bloqueio encontrado ao vivo** (São Carlos, `run_local --real --local-demo-admin`, "pizza para 2"):
busca OK (`ifood_mcp`, 10 ofertas), mas **as 3 chamadas de raciocínio falharam** (Curador, Estrategista,
resposta) → agentes caíram na regra de reserva e o bot voltou a sugerir "Pizza" de R$ 8,99 da esfiharia e
"Pastel de Pizza". Causa confirmada direto no OpenCode 1.19.3 (testes manuais, sem nosso código):

1. **`tools: {"*": false}` desliga a ferramenta interna `StructuredOutput`.** O OpenCode implementa
   `format: json_schema` como uma tool `StructuredOutput` ("You MUST use the StructuredOutput tool"). Sem
   ela: `info.error = StructuredOutputError: Model did not produce structured output`.
   **Correção (testada):** no raciocínio, `tools: {"*": false, "StructuredOutput": true}` e na sessão
   `permission: [{"permission":"*","pattern":"*","action":"deny"}, {"permission":"StructuredOutput","pattern":"*","action":"allow"}]`.
2. **O campo da resposta é `info.structured`**, não `info.structured_output` (o SDK documenta o outro nome).
   Teste: `info.structured = {"resposta": "ok"}`; a tool part `StructuredOutput` tem `state.input` igual e
   `metadata.valid = true`. **Correção:** ler `info.get("structured", info.get("structured_output"))` (e, como
   reserva, `state.input` da tool part `StructuredOutput`).
3. **`GET /session/{id}/message` responde 400** em sessões com `format` (bug de serialização do OpenCode:
   "Expected OutputFormatJsonSchema ... at [0].info.format"). Com `StructuredOutput: true`, o `run_prompt`
   considera "tools habilitadas" e faz esse GET → falharia. **Correção:** no raciocínio, não listar mensagens;
   usar o corpo do POST (`info` + `parts`).

Custo observado: **~8.400 tokens por chamada de raciocínio** (o OpenCode injeta o prompt do agente `build`).
Otimização futura: um agente OpenCode enxuto só para raciocínio.

Depois dessas 3 correções: abrir o PR da `feat/integrations` (já contém a `main`). O Claude testa ao vivo de novo.

## ✅ LISTA DO LORENZO — tudo que falta atualizar (Claude, 18/10/2026, `main@e700f39`)

PR #14 (agentes com IA) **já está na `main`**. Em ordem de prioridade:

1. **[FEITO em `e2f03b6`, MAS COM BUG — ver revisão acima] Runtime aceitar "chamada de raciocínio" sem ferramentas.**
   `RuntimeCall.allowed_tools == ()` e `max_tool_calls == 0` → rodar no OpenCode com todas as tools
   desligadas, `system=call.system`, `format: json_schema` com `call.output_schema`, respeitando `timeout_s`;
   devolver `RuntimeOutcome(ok=True, structured=<structured_output>, tool_calls=())`. Erros iguais aos da
   busca (`invalid_output`, `quota`, `timeout`, `unavailable`). Não passar por `SearchIntent`/`onlyOpen` nem
   marcar `ifood_mcp`. Hoje volta `tool_not_allowed` → os agentes usam a regra de reserva. Detalhes na seção
   "PRIORIDADE — Agentes passam a usar IA de verdade" logo abaixo.
2. **[FEITO na `feat/integrations`, falta PR] `backend/api/tests/test_acceptance.py:124`**: trocar
   `len(catalog.json()["agents"]) == 6` por `== 8` (novos: `curator`, `customer_memory`). Hoje: 1 failed,
   113 passed.
3. **[PRONTO, falta PR] Sua `feat/integrations` (`e86492c`, `8512f8d`)** — revisada pelo Claude e aprovada:
   gestor local no modo real (`--local-demo-admin`, só loopback) + **cookie `HttpOnly` para o SSE do
   navegador** (testado: SSE do gestor só com cookie recebeu 26 eventos; cliente e cookie falso → 403),
   `SQLiteMemory` padrão na API, modo de teste com lojas fechadas (pedido bloqueado com 409).
   Faça `git merge origin/main` (sem conflitos, testado), rode a suíte e abra o PR.
4. **[FEITO em `e2f03b6`] Afrouxar `SearchIntent.matches` agora que existe o Curador (IA).** Hoje o filtro por palavra
   corta "Big Mac"/"X-Bacon" para "hamburguer" **antes** de a IA ver. Proposta: manter `validate_query`
   (query limpa) mas não descartar itens por nome; o Curador decide relevância e o filtro por palavras dos
   agentes vira só reserva quando a IA falhar. Combinar antes de mexer.
5. **[OPCIONAL, só modo teste] Lojas fechadas no `--include-closed-restaurants`:** hoje o `is_open` é omitido
   para elas aparecerem, então os agentes não conseguem preferir as abertas quando há das duas. Sugestão:
   mandar `is_open: false` + tag de teste e os agentes rebaixam (Claude implementa a parte dos agentes).
6. **[PARA A LUANA, registrar no README da API]** O escritório deve chamar **uma vez**
   `GET /api/v1/admin/overview` com `X-Demo-Role: admin` (gera o cookie) e só depois abrir o `EventSource`.
7. **[NO FINAL] Trocar o modelo do OpenCode para Claude (API Anthropic)** — `OPENCODE_PROVIDER_ID`/
   `OPENCODE_MODEL_ID`; não precisa refazer o OAuth do iFood. Com IA em todos os agentes são ~4–5 chamadas
   de IA por pedido; o Gemini gratuito não aguenta uma demonstração inteira.

Já resolvido por você e conferido: `onlyOpen` + `is_open`, `SearchIntent` lendo `Produto desejado:`,
aviso curto no chat, xfail da retomada retirado, TTL de 5 min.

## PRIORIDADE — Agentes passam a usar IA de verdade (decisão do Gabriel, PR #14) (18/10/2026)

**Decisão do Gabriel:** os agentes estavam quase só por regras (a IA só montava a busca). Agora cada
especialista raciocina com IA e eles conversam de verdade. Regras ficam como guarda-corpo e reserva.

| Agente | O que a IA faz | Guarda-corpo (código) |
|---|---|---|
| **Curador** (`curator`, novo) | julga se cada item do iFood é o que o cliente pediu | só itens da busca; sem IA → filtro por palavras |
| **Memória do cliente** (`customer_memory`, novo) | responde aos outros agentes (histórico/preferências) | fatos com origem |
| Estrategista | pergunta à Memória + estratégia (RAG); escolhe ordem e argumento | só opções aprovadas; argumento sem números |
| Descontos | pergunta à Memória + política (RAG); decide sugerir/quanto | ≤ máximo da política; lucro no código; nunca aplica |
| Orquestrador | escreve a resposta ao cliente | restaurante e total exatos, sem outros valores, com avisos |

### → Lorenzo: o runtime precisa aceitar "chamada de raciocínio" (sem ferramentas)

Hoje `OpenCodeAgentRuntime._execute` recusa qualquer `RuntimeCall` sem `offer_search`
(`tool_not_allowed`) → os agentes caem na regra de reserva e **a IA não roda no modo real**.

**Contrato (já usado pelos agentes; nada muda em `ports.py`):**
- `RuntimeCall.allowed_tools == ()` e `max_tool_calls == 0` = **raciocínio sem ferramentas**.
- Executar o prompt no OpenCode com **todas as ferramentas desligadas** (`tools: {"*": false}`, permissão
  negando tudo), `system=call.system`, e saída estruturada `format: {"type": "json_schema", "schema":
  call.output_schema}`; `timeout_s` respeitado (abortar ao estourar).
- Devolver `RuntimeOutcome(ok=True, structured=<info.structured_output>, tool_calls=())`.
  Se o modelo não produzir JSON válido → `ok=False, error="invalid_output"`; 429 → `quota`; etc. (mesmos erros).
- **Não** passar por `SearchIntent`/`validate_query`/`onlyOpen` (não é busca) nem marcar `ifood_mcp`.
- Sem PII: os prompts levam só pedido, prato, itens/preços da busca, fatos agregados do cliente.
- Testes offline sugeridos: chamada sem ferramenta não chama `searchOffers`; JSON válido devolvido;
  JSON inválido → `invalid_output`; 429 → `quota`.

**Custo de cota:** ~4–5 chamadas de IA por pedido (curador, estrategista, descontos, resposta) + a busca.
Com Gemini gratuito acaba rápido; serve para validar e depois trocar para Claude (item 6 das decisões).
Retomada ("agora são 3 pessoas") reaproveita busca **e** julgamento do Curador (sem nova chamada a eles).

### → Lorenzo: teste a atualizar
`backend/api/tests/test_acceptance.py:124` conta 6 agentes; agora são **8** (`curator`, `customer_memory`).
É a única falha da suíte API com o PR #14 (113/124 passam com `main`/`feat/integrations`).

### Estado
PR #14 **mergeado na `main`** (`e700f39`). Agentes 123 testes OK (13 novos: Curador rejeita esfiha/pastel, IA não cria item,
reserva sem IA, desconto limitado à política, resposta com preço errado rejeitada, consultas à Memória).
Demo offline (`python3 -m backend.agents.demo --roteiro --escritorio`) mostra a conversa com **IA SIMULADA**.

## Novo: memória do cliente na `main` (Claude, PRs #12 e #13 — `4275a17`, `6c26ed6`)

- **`SQLiteCustomerMemory`** (porta `CustomerMemoryPort` em `backend/agents/ports.py`), em
  `backend/memory/customer_memory.py`: guarda por `(tenant_id, client_id)` só prato, quantidade, orçamento,
  atendimento e data — sem nome/contato/endereço. São **pedidos feitos ao bot, não compras confirmadas**.
  Calcula favoritos (prato em 2+ atendimentos), último pedido e orçamento típico por pessoa; `forget()` apaga.
- **No bot:** atendimento novo + "oi" → "Oi de novo! Da última vez você pediu X. Quer pedir o mesmo?";
  "quero o mesmo"/"de novo"/"o de sempre" repete prato, quantidade e orçamento; o estrategista prioriza o
  favorito (`pattern_identified`, `basis: "stated_preference"`); o gestor recebe `memory_changed`
  (`scope: "customer"`). Sessões sem `client_id` não são lembradas. O histórico fictício DEMO só entra
  quando não há histórico real.
- **Sem mudança na API:** `build_orchestrator` liga a memória do cliente padrão (uma por processo, em
  memória — vale enquanto a API estiver no ar, suficiente para a apresentação). Na demo, todas as sessões
  usam `client_demo_1`, então formam um histórico só.
- Testes: agentes 110 OK (11 novos), memória OK, API/integrations 114 passed, aceite 6/6. Pela API:
  atendimento 1 "pizza para 2" → atendimento 2 "oi" cita a pizza → "quero o mesmo" recomenda pizza para 2.
- **PR #13:** removidos 6 `.pyc` de `backend/memory/__pycache__` que entraram por engano (bloqueavam
  `git pull`) e criado `backend/memory/.gitignore`. **Se o seu `git pull` reclamar de `.pyc` em
  `backend/memory`, rode `git checkout -- backend/memory/__pycache__ backend/memory/tests/__pycache__`
  e puxe de novo** (são só cache).

## Decisões do Gabriel e prioridades até a apresentação (18/10/2026)

Para o Codex do Lorenzo. Substitui prioridades anteriores onde houver conflito.

| # | Item | Decisão |
|---|---|---|
| 1 | Painel do gestor em modo real (403 com `X-Demo-Role: admin`) | **Prioridade 1.** Sem isso o escritório fica vazio numa apresentação com dados reais. |
| 2 | Escritório ao vivo no navegador (SSE) | **Prioridade 2 — ver detalhe abaixo.** |
| 3 | Variedade das opções (filtro lexical rígido) | Em aberto; combinar Lorenzo + Claude antes de mexer (ver seção de validação abaixo). |
| 4 | `SQLiteMemory` ligada na API | **Não necessário.** A apresentação é uma execução contínua; memória temporária basta. Não priorizar. |
| 5 | Interface conectada à API | **Aguardando a Luana (frontend).** Nada a fazer no backend até a interface existir; manter o contrato v1. |
| 6 | Modelo de IA | **Manter Gemini durante os testes; trocar o modelo do OpenCode para Claude (API Anthropic) no final**, antes da apresentação. Não exige refazer o OAuth do iFood; muda provedor/modelo no OpenCode e `OPENCODE_PROVIDER_ID`/`OPENCODE_MODEL_ID`. Economizar chamadas reais até lá. |

### Item 2 em detalhe — o navegador não manda `X-Demo-Role` no SSE

O `EventSource` padrão do navegador **não permite cabeçalhos personalizados**. Então a conexão ao vivo
`GET /api/v1/sessions/{id}/events` sai sem `X-Demo-Role: admin` e o escritório recebe só a visão de
comprador (sem `agent_message`, `tool_activity`, `discount_proposed`...), **mesmo em modo demo**.
`/history` e `/snapshot` via `fetch` funcionam porque aceitam cabeçalho.

Opções (decidir com a Luana; a API é do Lorenzo):
- **Cookie de gestor de demonstração** (ex.: `GET /api/v1/demo/manager-login` que define cookie
  `HttpOnly` só em `127.0.0.1`/modo demo) — é o que o contrato recomenda (PROMPT §15.1: cookie
  same-origin para `EventSource`). Exige rota nova → acordo de contrato.
- **Frontend usar `fetch` + leitura de stream** em vez de `EventSource` (aceita cabeçalho; sem mudar a API).
- **Polling de `/history?after_seq=`** como reserva.

Não colocar credencial ou papel em query string (proibido no contrato).

## Validação do Claude na `main` — ao vivo, São Carlos, ~05h (18/10/2026)

Revisado e testado `main@6550f66` (PRs #9/#10) e publicado o ajuste do PR #11 (`1b8b95d`).
Offline: API/integrations **114 passed, 1 skipped**; agentes e memória OK; aceite HTTP demo 6/6.
`SearchIntent` conferido com as 4 frases da revisão: agora exige só o prato (`marmita parmegiana`,
`pizza`, `xis salada`) e nada em pedido genérico. Chat com um único aviso curto. Aprovado.

Ao vivo (`run_local --real`, OpenCode 1.19.3, `ifood connected (OAuth)`, Gemini):

| Mensagem (mesma sessão) | Buscas | Tempo | Resultado |
|---|---:|---:|---|
| "quero marmita parmegiana pra 2 pessoas por 100 conto no maximo, busque melhor preço" | 1 | 9 s | query `"marmita parmegiana"`, `onlyOpen: true`, `sort: RELEVANCE`, `pageSize: 20`; **iFood devolveu 0** ("no results with the active filters in this area") → bot não inventa; frase agora cita o prato (PR #11) |
| "quero hamburguer pra 2 pessoas até R$ 100" | 1 | 8 s | 20 resultados, **todos `isOpen: true`**; "2x O Seu Hambúrguer Perfeito!", R$ 35,08, `ifood_mcp` |
| "agora são 3 pessoas" | **0** | 2 s | **retomada funcionou ao vivo**: 3x, R$ 52,62, sem chamar Gemini/iFood |

Prato pedido, lojas abertas, preço unitário e reaproveitamento: **confirmados ao vivo.**

### Pendente para decidir junto (Lorenzo + Claude): variedade das opções

Para "hamburguer", o iFood devolveu 20 itens de 4 restaurantes (Big Mac, Rodeio do Burger King,
X-Bacon, X-Salada...), mas **só 1 opção chegou ao cliente**: `SearchIntent.matches` exige o termo no
nome do item, e "Big Mac"/"X-Bacon" não contêm "hamburguer". O filtro de relevância dos agentes tem a
mesma limitação (mais branda: também aceita o nome do restaurante). É o custo do filtro rígido que
corrigiu o caso "2 Tortas". Proposta: agora que a query vai limpa com `sort: RELEVANCE` e `onlyOpen`,
confiar mais na relevância do iFood e filtrar só o claramente sem relação — **as duas camadas precisam
mudar juntas**; ninguém altera sozinho. Sem lista fixa de comidas.

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

</details>
