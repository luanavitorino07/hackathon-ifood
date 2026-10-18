# PedIA — React Native + TypeScript

A seta no cabeçalho do chat abre o escritório (primeiro a **Visão do CEO**); “Abrir chatbot” retorna à conversa.

**Visão do CEO** (`src/screens/CeoScreen.tsx` + `src/services/executive.ts`): indicadores executivos
calculados a partir do histórico real dos atendimentos recentes (gestor): atendimentos, taxa de
recomendação, ticket médio, valor recomendado, tempo médio de resposta, funil, uso e falhas da IA
(com alerta de cota), buscas no iFood e buscas economizadas pela retomada, descontos sugeridos,
conflitos, pratos e restaurantes mais frequentes, decisões recentes e destaques da IA. Sem dado, mostra “—”.

Frontend Expo para o chatbot comprador e o escritório comercial. O design original foi preservado na integração; os ajustes são de conexão, estado e entrada de áudio. API real é o padrão; mocks exigem habilitação explícita.

## Estrutura integrada

A pasta `frontend/` já faz parte do repositório. Não copiar backend antigo por cima do atual.

```text
hackathon-ifood/
├── backend/                       # existente, sem alterações
└── frontend/
    ├── App.tsx                    # navegação responsiva das quatro telas
    ├── app.json
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    ├── .env.example
    ├── scripts/
    │   ├── proxy.mjs              # mesma origem para Expo Web + API
    │   └── check_backend.py       # smoke test HTTP e validação dos mocks
    └── src/
        ├── components/
        │   ├── AgentGraph.tsx     # relações geradas de agent_message
        │   └── ui.tsx             # cards, métricas, botões e recomendação
        ├── hooks/useSession.ts    # snapshot, SSE, histórico e recuperação
        ├── mocks/
        │   ├── agents.json        # catálogo com seis agentes
        │   ├── events.json        # sequência v1 completa + conflitos
        │   └── server.ts          # sessão, chat, pedido e overview em memória
        ├── screens/
        │   ├── ChatScreen.tsx
        │   └── OfficeScreen.tsx   # Dashboard, Painel de Agentes e Conflitos
        ├── services/
        │   ├── api.ts             # todos os endpoints v1 + SSE
        │   ├── state.ts           # projeção, deduplicação e conflitos
        │   └── state.test.ts
        ├── theme/index.ts
        └── types/api.ts           # DTOs derivados dos modelos Pydantic
```

## 1. Executar com mocks, sem backend

Requer Node 20.19+ e npm.

```bash
cd frontend
npm ci
cp .env.example .env
EXPO_PUBLIC_USE_MOCKS=true npm run web
```

Abra o endereço mostrado pelo Expo (normalmente http://localhost:8081). Para celular, `npm start` e abra no Expo Go compatível com SDK 54. Os mocks são locais ao processo do aplicativo, não se sincronizam entre abas ou aparelhos e se perdem ao recarregar.

Roteiro: abra Dashboard/Painel/Conflitos para inspecionar `sess_1`; no Chatbot, envie um pedido para quatro pessoas até R$ 120. O mock responde após um pequeno atraso, oferece uma recomendação por R$ 118,00, permite revisar e confirmar uma submissão simulada. Há um conflito resolvido e outro aberto na sessão de exemplo.

O seletor Chatbot/gestão serve à demonstração. A autorização efetiva é feita pelo backend; esconder uma aba não é controle de acesso. Novos agentes aparecem pelo catálogo sem alterar o código.

## 2. Conectar ao backend existente no navegador

No arquivo `.env`:

```dotenv
EXPO_PUBLIC_USE_MOCKS=false
EXPO_PUBLIC_API_URL=/api/v1
EXPO_PUBLIC_DEMO_ADMIN=true
```

Terminal 1, na raiz do repositório:

```bash
# No ambiente Python da API: requer ffmpeg instalado no sistema
python -m pip install -r backend/integrations/requirements-stt.txt
# OpenCode configurado/autorizado deve estar em execução na porta 4096.
APP_STT_PROVIDER=whisper APP_STT_MODEL=small python -m backend.api.run_local --real --local-demo-admin
```

Para o ensaio fora do horário de atendimento, acrescente `--include-closed-restaurants`.
Isso permite analisar catálogo real de lojas fechadas, sempre com aviso e sem permitir pedido.
Para demo offline, use `python -m backend.api.run_local` sem `--real`.

Terminal 2:

```bash
cd frontend
npm run web
```

Terminal 3:

```bash
cd frontend
npm run proxy
```

Abra **http://localhost:8080**. O proxy encaminha `/api/` ao backend e as demais rotas ao Expo, inclusive WebSocket. Isso evita alterar o CORS da equipe de backend. Acesse 8080, não 8081, para usar `/api/v1` com a API conectada.

Ao mudar `.env`, reinicie o Expo; se necessário, `npm run web -- --clear`. A conexão não troca silenciosamente para mocks quando há erro.

O cliente administrativo envia `X-Demo-Role: admin` no HTTP e SSE; o comprador envia explicitamente
`X-Demo-Role: customer`, para não herdar o cookie do escritório. No modo real, o papel de gestor
local exige `--local-demo-admin` e conexão loopback. É uma identidade de demonstração local,
não autenticação de produção. Variáveis `EXPO_PUBLIC_*` são públicas: nunca colocar chaves nelas.
`EXPO_PUBLIC_DEMO_ADMIN=false` desativa esses cabeçalhos para uma integração futura com autenticação real.

## 3. Celular / emulador

No `.env`, use uma URL absoluta acessível ao aparelho:

```dotenv
EXPO_PUBLIC_USE_MOCKS=false
EXPO_PUBLIC_API_URL=http://192.168.1.10:8000/api/v1
EXPO_PUBLIC_DEMO_ADMIN=true
```

Troque o IP pelo do seu computador. Inicie a API com `--host 0.0.0.0` apenas na rede local de teste. Android Emulator normalmente usa `http://10.0.2.2:8000/api/v1`. No aparelho físico, `localhost` é o próprio celular. O proxy de navegador não é necessário para chamadas nativas.

## Telas e dados

- **Chatbot:** mensagens, arquivo de áudio e microfone no navegador, revisão/edição da transcrição,
  recomendações, composição de preços e eventos. Toque no microfone para iniciar e novamente
  para parar; aguarde a transcrição, revise e envie. `transcription_id` é enviado automaticamente.
  Gravação exige permissão e localhost/HTTPS. O texto não dispara busca antes da confirmação.
  O áudio tem limite de 120 s/10 MiB; a gravação para em 115 s. O arquivo original não é persistido.
- **Sessão:** recuperada no refresh da aba enquanto a API mantém a sessão; após reinício do backend,
  um ID inexistente gera nova sessão. “Novo atendimento” inicia outra conversa sem apagar a anterior.
- **Dashboard:** métricas de overview, sessões recentes, catálogo e conflitos da sessão selecionada.
- **Painel de Agentes:** estado por sessão, eventos por agente, falhas de ferramentas, justificativas exatas, comunicações por destinatário, grafo, histórico, interação com comprador, recomendações, decisões, RAG, memória e padrões.
- **Conflitos:** contagem e filtros todos/abertos/resolvidos. Uma resolução atualiza o conflito existente pelo ID, em vez de contar um conflito novo.

`202` apenas indica aceite. A interface aguarda eventos para mostrar respostas e status de pedidos. IDs de mensagem são preservados em tentativas do mesmo envio. A confirmação de pedido mantém o ID em caso de falha para permitir reenvio idempotente.

A sessão abre por snapshot. O histórico paginado reconstrói eventos anteriores, e SSE acompanha novos eventos com `after_seq`. Uma consulta ao histórico a cada 2,5 segundos também recupera falhas de conexão. Eventos repetidos são deduplicados; sequências são tratadas por sessão. A visão geral é atualizada a cada cinco segundos.

## Diferenças das imagens impostas pelo contrato

- Preço original, imagem, faixa de entrega, distância, avaliação e abertura já existem no contrato
  atualizado e nos tipos do frontend; valores ausentes são nulos. A apresentação original dos cards
  foi preservada, com aviso adicional para restaurante fechado; não são usadas fotos inventadas.
- Não há categorias padronizadas de razões: são exibidas frequências dos textos exatos, não percentuais inventados como “60% por localização”.
- Não há lucro/orçamento por sessão nem valor médio oficial do pedido: valores ausentes ficam “Indisponível”. Não somamos recomendações como receita.
- As métricas gerais vêm de overview; conflitos/estatísticas individuais se referem à sessão selecionada e aos eventos carregados.
- O estado de agente é local ao atendimento, não uma indicação global de funcionamento.
- Não há endpoint para resolver conflitos, aprovar descontos ou emitir relatórios: não criamos botões que finjam executar essas ações.

## Pendências do backend atual

Áudio funciona com Whisper local quando `APP_STT_PROVIDER=whisper`; sem essa opção retorna
`503 STT_UNAVAILABLE`. O modelo small precisa ser baixado uma vez; veja `backend/integrations/AUDIO.md`.
Submissão real continua indisponível (`503 ORDER_SUBMISSION_UNAVAILABLE`): a revisão do pedido avisa
esse limite e não habilita o botão de envio real. Restaurantes fechados não podem ser selecionados.
Carrinho e atualizações de pedido são renderizados se eventos chegarem, mas não foram inventados
dispatchers/transações reais. Mocks permitem somente demonstração explicitamente simulada.

Autenticação de produção e CSRF continuam pendentes. Nenhuma compra real é feita pelo teste de integração.

## Verificações

```bash
cd frontend
npm run typecheck
npm test
npm run export:web
```

Na raiz, com as dependências Python do projeto instaladas:

```bash
uv run python frontend/scripts/check_backend.py
```

Valida fixtures nos modelos Pydantic e testa API demo: catálogo, sessão, chat, idempotência, recomendações, histórico, privacidade, overview e erros de áudio/pedido indisponíveis. Os testes TypeScript cobrem replay, isolamento de sessão, conflitos resolvidos, visibilidade e comportamento assíncrono dos mocks. Build Web e tipos foram verificados; não foi realizado teste visual em dispositivo físico.
