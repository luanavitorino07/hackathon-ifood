# PedIA — React Native + TypeScript

Atualização visual: veja `ATUALIZAR_VISUAL.md` para aplicar a versão com Inter, degradês e layout mais próximo dos protótipos. A seta no cabeçalho do chat abre o escritório; “Abrir chatbot” retorna à conversa.

Frontend Expo para o chatbot comprador e o escritório comercial, baseado nas quatro referências enviadas. Responsivo: menu lateral no desktop e superior no celular. Compatível com o contrato v1 e com `main` do backend em `88d88e8`.

## Colocar no repositório

Copie a pasta `frontend/` deste pacote para a raiz do seu `hackathon-ifood/`, ao lado de `backend/`. Não substitua arquivos do backend. Nenhuma mudança nas rotas ou payloads é necessária. Esta entrega não fez push no GitHub.

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
npm run web
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
uv run --python 3.12 uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

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

O cliente administrativo envia `X-Demo-Role: admin` no HTTP e no SSE; o comprador não envia. Esse mecanismo só existe no modo demo do backend. Em modo real, é necessário o resolvedor de identidade autenticado da equipe e cookies da aplicação. Variáveis `EXPO_PUBLIC_*` são públicas: nunca coloque credenciais nelas. A opção de CSRF presente no cliente é um ponto de integração para o mecanismo que o backend vier a disponibilizar.

## 3. Celular / emulador

No `.env`, use uma URL absoluta acessível ao aparelho:

```dotenv
EXPO_PUBLIC_USE_MOCKS=false
EXPO_PUBLIC_API_URL=http://192.168.1.10:8000/api/v1
EXPO_PUBLIC_DEMO_ADMIN=true
```

Troque o IP pelo do seu computador. Inicie a API com `--host 0.0.0.0` apenas na rede local de teste. Android Emulator normalmente usa `http://10.0.2.2:8000/api/v1`. No aparelho físico, `localhost` é o próprio celular. O proxy de navegador não é necessário para chamadas nativas.

## Telas e dados

- **Chatbot:** mensagens, envio de arquivo de áudio, revisão/edição da transcrição, recomendações, composição de preços, confirmação explícita e resultado assíncrono do pedido. Áudio usa seletor de arquivo, sem gravador embutido.
- **Dashboard:** métricas de overview, sessões recentes, catálogo e conflitos da sessão selecionada.
- **Painel de Agentes:** estado por sessão, eventos por agente, falhas de ferramentas, justificativas exatas, comunicações por destinatário, grafo, histórico, interação com comprador, recomendações, decisões, RAG, memória e padrões.
- **Conflitos:** contagem e filtros todos/abertos/resolvidos. Uma resolução atualiza o conflito existente pelo ID, em vez de contar um conflito novo.

`202` apenas indica aceite. A interface aguarda eventos para mostrar respostas e status de pedidos. IDs de mensagem são preservados em tentativas do mesmo envio. A confirmação de pedido mantém o ID em caso de falha para permitir reenvio idempotente.

A sessão abre por snapshot. O histórico paginado reconstrói eventos anteriores, e SSE acompanha novos eventos com `after_seq`. Uma consulta ao histórico a cada 2,5 segundos também recupera falhas de conexão. Eventos repetidos são deduplicados; sequências são tratadas por sessão. A visão geral é atualizada a cada cinco segundos.

## Diferenças das imagens impostas pelo contrato

- Não há foto de produto no contrato: a recomendação usa um marcador visual, sem associar foto fictícia a produto real.
- Não há categorias padronizadas de razões: são exibidas frequências dos textos exatos, não percentuais inventados como “60% por localização”.
- Não há lucro/orçamento por sessão nem valor médio oficial do pedido: valores ausentes ficam “Indisponível”. Não somamos recomendações como receita.
- As métricas gerais vêm de overview; conflitos/estatísticas individuais se referem à sessão selecionada e aos eventos carregados.
- O estado de agente é local ao atendimento, não uma indicação global de funcionamento.
- Não há endpoint para resolver conflitos, aprovar descontos ou emitir relatórios: não criamos botões que finjam executar essas ações.

## Pendências do backend atual

No checkout validado, transcrição retorna `503 STT_UNAVAILABLE` e submissão retorna `503 ORDER_SUBMISSION_UNAVAILABLE`. Os consumidores frontend estão implementados, mas essas capacidades dependem de provedores/dispatchers configurados pelo backend. Os mocks permitem testar os fluxos simulados. A interface exibe o erro sem anunciar sucesso.

Autenticação de produção do gestor e CSRF também precisam da composição de identidade do backend. Nenhuma compra ou consulta MCP real foi executada para validar esta entrega.

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
