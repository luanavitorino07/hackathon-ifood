# API — execução local e integração com agentes

Esta composição exige `backend.agents` da branch `feat/agents` (validada contra
`784b57c`). Essa dependência ainda não está na branch `feat/integrations`.
Integre as branches pelo fluxo de revisão da equipe antes de executar diretamente
o comando abaixo. Para validação isolada, também é possível disponibilizar uma
cópia de `backend/agents` em outra pasta adicionada ao `PYTHONPATH`.

Na raiz do projeto, com as dependências instaladas:

```text
uv run --python 3.12 uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Documentação interativa: http://127.0.0.1:8000/docs (com o servidor iniciado).

## Runtime

- `APP_RUNTIME_MODE=demo` (padrão): catálogo fictício dos agentes, sem rede,
  sem Gemini e sem OpenCode. Sessões/eventos/ofertas identificados como demo.
- `APP_RUNTIME_MODE=real`: usa `OpenCodeAgentRuntime` e exige OpenCode Server,
  provedor Google, OAuth iFood e localização configurados localmente. A origem
  `ifood_mcp` continua exigindo prova de sucesso da ferramenta. Não há fallback
  silencioso de real para demo. Valores de modo inválidos interrompem a inicialização.

No Prompt de Comando do Windows, selecione com `set APP_RUNTIME_MODE=demo`
antes de executar o servidor; para o runtime real, use `set APP_RUNTIME_MODE=real`.

## Identidade e painel da demonstração

Na demo, o comprador é `client_demo_1`. O gestor usa `X-Demo-Role: admin` nas
requisições de catálogo, overview, histórico, snapshot e SSE. Isso é um seletor
de papel para demonstração local, não autenticação de produção.

O frontend precisa enviar o cabeçalho também ao consumir SSE (por exemplo, com
streaming via fetch; EventSource nativo não permite definir cabeçalhos próprios).
Não enviar esse cabeçalho nas chamadas do comprador.

No modo real, o cabeçalho é ignorado. A identidade padrão continua sendo a
identidade local de comprador; autenticação real e perfil de gestor exigem
`build_application(identity_resolver=...)`. Não publicar como serviço de produção.

## Contexto inicial

`POST /api/v1/sessions` aceita `initial_context` omitido ou nulo. Quando fornecido,
deve conter exatamente `name`, `age`, `location`, `preferences`, `restrictions`:

```json
{"client_id":null,"initial_context":{"name":null,"age":null,"location":null,"preferences":["pizza"],"restrictions":[]}}
```

Idade deve ser inteiro de 0 a 130 ou null. Nome/localização são strings não vazias
ou null; preferências/restrições são listas de strings não vazias.

O contexto é salvo com revisão esperada 0 e autor `api` antes de publicar a sessão.
API e agentes compartilham `app.state.memory` / `app.state.agent_services.memory`.
Cada mensagem carrega novamente o contexto da memória e encaminha o modo da sessão.
Para memória persistente, injete `build_application(memory=...)`; o padrão é efêmero.

## Aceite e pendência externa

`tests/test_acceptance.py` verifica catálogo de seis agentes, pedido de quatro
pessoas por R$ 115,60, validação e propagação do contexto, modos, isolamento do
comprador/gestor e SSE sobre HTTP local.

O aceite exato “quero comida para 2 pessoas até R$ 200” com preferência “pizza”
tem regressão reproduzida em `agents@784b57c`: a busca de demonstração filtra
“comida” para pratos caseiros e não retorna pizza. O contexto chega corretamente
à memória/constraints. O caso está marcado `xfail(strict=True)` para acompanhamento,
não como aceite aprovado. Com “quero pizza para 2 pessoas até R$ 200”, a mesma
API retorna a frase de preferência solicitada.

Correção proposta ao responsável pelos agentes: considerar as preferências na
busca genérica do catálogo demo, preservando as restrições e mensagens explícitas.
Nenhum arquivo de agentes foi alterado. A busca iFood real ainda requer teste com
OAuth e resultado sanitizado; áudio e envio real de pedidos continuam pendentes.
