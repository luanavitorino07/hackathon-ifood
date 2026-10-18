# API — execução local e integração com agentes

Esta composição já inclui `backend.agents` integrado de `feat/agents@9c7180a`.
API, runtime e os seis agentes estão no mesmo checkout; não é mais necessário
exportar os agentes para uma pasta temporária ou configurar um `PYTHONPATH` extra.
O módulo `backend/memory` (SQLite e RAG) entrou na `main` pelo PR #3. O RAG já é
composto pelos agentes; a API ainda usa memória operacional temporária por padrão.
É possível injetar `SQLiteMemory` em `build_application(memory=...)`, mas isso não
persiste o cadastro de sessões HTTP, projeções, histórico SSE ou idempotência da API.

Na raiz do projeto, com as dependências instaladas:

```text
uv run --python 3.12 uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Documentação interativa: http://127.0.0.1:8000/docs (com o servidor iniciado).

Por padrão, a API inicia em demo, sem consumir cota de Gemini/Claude. Para validar
os módulos juntos offline:

```text
uv run --python 3.12 pytest backend/api/tests backend/integrations/tests backend/agents/tests -q
```

O teste real continua desabilitado, salvo `RUN_LIVE_IFOOD=1` explícito. Os testes
offline cobrem conversa, seis agentes, preferência por pizza, orçamento/restrições,
contexto compartilhado e isolamento de eventos HTTP/SSE entre comprador e gestor.

## Qualidade e limites da busca

O runtime real protege a especificidade do pedido com uma guarda lexical: a query
e os nomes dos itens devem manter os termos significativos do prato solicitado.
Não há lista fechada de pratos. Retorno de strogonoff não é promovido a parmegiana
de frango; se nada corresponder, a lista fica vazia, sem pesquisa extra automática.
Isso é conservador: sinônimos não normalizados, descrições incompletas e consultas
complexas precisam de alinhamento da intenção estruturada com o pesquisador.

As ofertas compatíveis são deduplicadas por produto/loja e distribuídas entre os
restaurantes retornados. Não são inventadas outras lojas nem ampliadas permissões
ou chamadas. O retorno existente já contém preço unitário em centavos e mantém a
promoção informada pelo MCP; personalização não confirmada não vira adicional cobrado.

O schema oficial de entrada foi consultado por `tools/list`: as buscas exigem
`refinements.onlyOpen=true` e pedem `pageSize=20` (máximo oficial 25), em uma chamada.
O runtime confere que o filtro foi realmente enviado e descarta defensivamente
itens com `merchant.isOpen=false`; booleano verdadeiro é repassado como `is_open`.
Se todas as lojas estiverem fechadas, devolve lista vazia. Ausência do status não
vira um booleano verdadeiro inventado. Abertura é referida ao momento da consulta.

Avisos de entrega ainda não garantida, distância, ingredientes, alterações e preço
dos complementos não confirmados são preservados em `Recommendation.warnings` e no chat.
Uma busca com coordenadas públicas não confirma entrega no endereço do usuário.
Não foram criados campos HTTP de modificadores nem novas ferramentas MCP.

Os avisos são associados a sessão/produto/loja por um armazenamento efêmero limitado
e com validade de cinco minutos, sem guardar prompt, endereço, credenciais ou retorno
bruto. Isso não é cache de ofertas e não implementa a retomada dos agentes.

O token antigo inicialmente recebeu HTTP 401. O diagnóstico OAuth do OpenCode
conseguiu reconectar, e a listagem autenticada de ferramentas voltou a responder.
O schema sanitizado está em `backend/integrations/tests/fixtures/ifood_search_input_schema.json`.
Uma busca direta somente leitura também validou `onlyOpen=true` em São Carlos:
20 resultados, todos com `merchant.isOpen=true`, sem Gemini. Isso não é teste do
fluxo completo via API/Gemini; a suíte automatizada usa OpenCode/MCP simulados.

O catálogo e o classificador do modo demo pertencem a `backend/agents`; as correções
de relevância e retomada do Claude (PRs #6/#7) foram integradas nesta branch.
Correspondência lexical continua limitada para sinônimos e descrições incompletas;
o alinhamento com os agentes está registrado em `ATUALIZACAO.md`.

## Runtime

### Credenciais locais do OpenCode

O `opencode.json` aponta para dois arquivos privados, ignorados pelo Git:
`backend/integrations/.local/ifood-client-id.txt` e
`backend/integrations/.local/ifood-client-secret.txt`.
Em um checkout novo, crie os arquivos com os valores do mesmo cliente OAuth
antes de iniciar o OpenCode. Eles não são incluídos nos commits. O callback
configurado é `http://localhost:8080/callback`, igual ao aprovado no portal deste
agente; outro cliente pode exigir outro endereço previamente cadastrado.
O Gemini/Anthropic é conectado separadamente pelo provedor no OpenCode.

- `APP_RUNTIME_MODE=demo` (padrão): catálogo fictício dos agentes, sem rede,
  sem Gemini e sem OpenCode. Sessões/eventos/ofertas identificados como demo.
- `APP_RUNTIME_MODE=real`: usa `OpenCodeAgentRuntime` e exige OpenCode Server,
  provedor Google, OAuth iFood e localização configurados localmente. A origem
  `ifood_mcp` continua exigindo prova de sucesso da ferramenta. Não há fallback
  silencioso de real para demo. Valores de modo inválidos interrompem a inicialização.

O modelo padrão do runtime agora é `google/gemini-3.8-flash`, variante `low`.
O Google recusou `gemini-2.5-flash` para o cadastro usado na validação real.
Sobrescreva com `OPENCODE_MODEL_ID` e `OPENCODE_MODEL_VARIANT` se necessário.

OpenCode `1.19.3` não inclui tools MCP em `/experimental/tool/ids`. O cliente usa
`OPENCODE_IFOOD_SEARCH_TOOL_ID` (padrão `ifood_searchOffers`, confirmado no ambiente)
quando `/mcp` confirma conexão. A execução ainda precisa comprovar uma chamada real
concluída. Todas as outras ferramentas são negadas por wildcard e por permissões
da sessão. O cliente reúne as mensagens intermediárias da mesma execução para
recuperar o resultado MCP, sem confiar apenas no texto final do modelo.

O filtro alimentar real é `refinements.itemRestrictions`, não `dietary`.
Tags alimentares continuam desconhecidas quando ausentes no resultado do iFood.

### Executar a integração real localmente (Prompt de Comando)

Com os agentes já integrados no checkout, OpenCode autenticado
no mesmo projeto e servidor OpenCode iniciado em `127.0.0.1:4096`:

```bat
set APP_RUNTIME_MODE=real
set IFOOD_SANDBOX_LATITUDE=-22.0175
set IFOOD_SANDBOX_LONGITUDE=-47.89083333
set IFOOD_FALLBACK_LOCATION_SOURCE=public_test
uv run --python 3.12 uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Essas coordenadas são referência pública de teste em São Carlos/SP, NÃO um sandbox
confirmado nem a localização do comprador. `public_test` registra essa distinção
no resumo de atividade. Para um sandbox oficial, configure suas coordenadas e
`IFOOD_FALLBACK_LOCATION_SOURCE=sandbox`. Sem localização válida, a busca falha
explicitamente com `LOCATION_REQUIRED`. Os comandos acima alteram só o processo
do terminal, não as variáveis permanentes do Windows.

Para evitar herdar as coordenadas antigas de São Paulo, o launcher local já
seleciona São Carlos e vincula o servidor somente a `127.0.0.1`:

```text
python -m backend.api.run_local --real
```

Sem `--real`, esse comando inicia em demo, sem consumir IA. O launcher limpa
coordenadas antigas somente do seu processo; não altera configurações permanentes
do computador. Um servidor já iniciado precisa ser reiniciado com esse comando.
Também existe o preset opt-in `IFOOD_TEST_LOCATION=sao_carlos`; fora do launcher,
coordenadas explícitas no ambiente têm prioridade. Sem preset nem coordenadas,
o backend continua sem presumir localização. Coordenadas válidas no contexto do
runtime prevalecem sobre o fallback de teste. Texto "São Carlos" sozinho não é geocodificado.

Referência pública aproximada da cidade:
[GeoNames](https://www.geonames.org/advanced-search.html?country=BR&q=Sao+Carlos).
Não é um endereço de entrega e não confirma cobertura do iFood; para entrega real,
é necessário fornecer/validar a localização específica do comprador.

### Continuidade e reenvios

Reenvios HTTP com o mesmo `session_id` e `client_message_id` agora retornam o aceite
anterior sem agendar os agentes de novo, inclusive em envios simultâneos. Conteúdo
diferente no mesmo ID continua retornando `409`. Essa garantia é local ao processo;
o estado HTTP ainda não está persistido. Para nova tentativa explícita após falha,
envie uma mensagem com ID novo.

A retomada foi implementada pelo Claude nos agentes (PR #7): candidatos válidos
do mesmo atendimento são reidratados quando só muda quantidade ou orçamento.
Os testes HTTP de retomada passam normalmente com memória efêmera e SQLite,
sem `xfail`, incluindo alteração de orçamento e quantidade em sequência. Isso não
equivale a persistir todo o atendimento HTTP entre reinícios.

Em outro terminal, o teste de fumaça real é opt-in:

```bat
set RUN_LIVE_IFOOD=1
uv run --python 3.12 pytest backend/api/tests/test_live_ifood.py -q
```

Esse teste faz busca somente leitura e verifica HTTP, recomendações `ifood_mcp`,
histórico e SSE do comprador. A execução normal dos testes não chama serviços reais.

### Evidência da validação real

Validação com agentes `784b57c` carregados de uma cópia temporária somente leitura,
sem merge e sem alterar seu código. Fluxo exercitado: HTTP → orquestrador →
pesquisador → OpenCode → Gemini 3.8 Flash → searchOffers → planejador/auditor →
snapshot/histórico/SSE. Foram verificadas separadamente as visões comprador e
gestor usando um resolvedor de identidade restrito ao teste local.

A busca de pizza retornou cinco ofertas reais e três recomendações. Exemplo:
Pizzaria Rancho da Pizza, pizza grande com bebida, R$ 38,98 e entrega informada
em 40 minutos. O valor NÃO inclui taxa de serviço desconhecida; esse aviso foi
preservado na recomendação e na fala do assistente. Nenhuma compra foi executada.

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
Para memória persistente, injete `build_application(memory=...)`; o padrão é
`EphemeralSessionMemory`, em `backend/api/session_memory.py`, com isolamento de
sessões, cópias defensivas e controle de revisão. Não possui banco/RAG, perde os
dados ao reiniciar e não depende de `backend.agents.testing.fakes`.

## Aceite e pendências

`tests/test_acceptance.py` verifica catálogo de seis agentes, pedido de quatro
pessoas por R$ 115,60, validação e propagação do contexto, modos, isolamento do
comprador/gestor e SSE sobre HTTP local.

O aceite exato “quero comida para 2 pessoas até R$ 200” com preferência “pizza”
foi corrigido pelo responsável pelos agentes em `9c7180a` e agora é um teste de
regressão normal, sem `xfail`. O merge preserva o código recebido dos agentes;
as adaptações de composição ficam em `backend/api`.

A busca iFood real por pizza foi validada anteriormente
com OAuth, agentes, HTTP e SSE. Áudio e envio real de pedidos continuam pendentes.
As duas tentativas ao vivo de pedido vegetariano excederam 60 segundos antes da
chamada MCP (`LLM_TIMEOUT`); o filtro `itemRestrictions` está coberto pelos testes,
mas sua execução real ainda precisa ser confirmada. Não foram inventadas ofertas
para contornar essas falhas.

Diagnóstico posterior das repetições: uma chamada mínima diretamente ao Google,
usando a mesma chave local sem exibi-la, confirmou HTTP 429 `RESOURCE_EXHAUSTED`.
O provedor informou limite de 20 solicitações para `gemini-3.8-flash` e espera de
cerca de 21h35 naquele momento. A repetição do teste de fumaça também falhou por
ausência de resultado dentro do prazo. O primeiro fluxo real completo passou;
não considerar as repetições nem o filtro vegetariano aprovados enquanto a cota
não for restabelecida. O cliente normaliza 429 para quota quando o OpenCode expõe
o erro; se o OpenCode fica aguardando internamente, o deadline continua produzindo
`LLM_TIMEOUT` e abortando a execução, sem promover dados simulados a dados reais.
