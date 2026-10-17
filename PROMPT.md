# Escritório Virtual Multiagente — Hackathon iFood

> **Este arquivo é a especificação principal do produto para uma IA de programação.** Leia-o antes de propor arquitetura, criar arquivos ou implementar funcionalidades. Preserve o escopo: o objetivo é um MVP demonstrável em aproximadamente 18 horas, não um sistema completo de produção.

## 1. Conceito e público

Criar um **escritório virtual de agentes de IA** que trabalha nos bastidores de um **chatbot vendedor**. O consumidor conversa com o chatbot **por texto ou áudio** para escolher e realizar pedidos. Áudios enviados pelo cliente devem ser transcritos e processados pelo mesmo fluxo de mensagens de texto. Agentes especializados pesquisam opções, analisam preferências, montam propostas de compra, avaliam estratégias de venda e sugerem descontos quando fizer sentido econômico.

A empresa contratante (inicialmente uma plataforma de compras conectada ao iFood, mas com arquitetura adaptável a outras empresas) tem uma segunda interface: um **escritório virtual visual para o gestor comercial / diretor de vendas**. Ele acompanha os agentes, **a comunicação entre eles**, o andamento dos atendimentos, as decisões e suas justificativas. **O consumidor não vê o escritório interno**; só vê o chatbot e as recomendações relevantes à compra.

Objetivos simultâneos:
- **Para o consumidor:** recomendar pedidos adequados ao orçamento, às restrições, às preferências e às opções realmente disponíveis.
- **Para a empresa:** melhorar conversão e **lucro esperado** com personalização, estratégias de vendas e sugestões de desconto baseadas em dados, sem desrespeitar o que o cliente pediu.
- **Para a gestão:** tornar a operação multiagente **visível, auditável e extensível**.

Não presumir que a empresa poderá modificar preços ou descontos no iFood: sugerir descontos e aplicá-los são ações distintas.

## 2. Fluxo da compra

1. O consumidor explica o pedido pelo chatbot por texto **ou mensagem de áudio**; pode informar preferências, restrições, quantidade e orçamento. Se vier em áudio, transcrever primeiro e pedir confirmação/ajuste quando a transcrição for incerta ou envolver dados críticos.
2. O **orquestrador** consulta o estado compartilhado da sessão e decide quais especialistas são necessários. Perguntas simples não devem acionar todos os agentes.
3. O **pesquisador** consulta opções disponíveis pelas ferramentas MCP do iFood.
4. O **planejador** monta e compara pedidos possíveis; consulta preferências e padrões relevantes do cliente, se existirem e se o uso for permitido.
5. O **estrategista de vendas** avalia como apresentar as opções para melhorar a conversão e a rentabilidade. O **especialista em descontos** pode propor incentivos, mas só com margens/regras confiáveis e dentro das permissões.
6. O **auditor** verifica restrições, inconsistências, dados faltantes, conflitos entre propostas e as justificativas registradas. O orquestrador solicita revisão ou esclarecimentos quando necessário.
7. O chatbot apresenta uma recomendação fundamentada ao consumidor. Após confirmação explícita, monta o carrinho ou avança na compra usando somente ferramentas autorizadas. A resposta pode ser em texto mesmo quando o cliente usar áudio; síntese de voz não é necessária no MVP.
8. Durante o processo, o escritório visual da gestão comercial mostra as **comunicações e os eventos reais** dos agentes, sem precisar conhecer a lógica interna de cada um.

Exemplo de cenário de demonstração: “Quero comida para quatro pessoas, até R$ 120, com uma opção vegetariana”. O sistema pesquisa ofertas, propõe combinações, verifica restrições, avalia se há alguma promoção apropriada, justifica a escolha e prepara o carrinho com confirmação do cliente.

## 3. Mensagens de áudio (entrada de voz)

O **chatbot do consumidor deve aceitar texto e mensagens de áudio em português brasileiro**. Para o MVP, permitir o envio de um arquivo ou gravação de voz pela interface, usando formatos comuns suportados pelo serviço de transcrição escolhido. **Não exigir conversa de voz em tempo real nem resposta falada.**

Fluxo **único**: `áudio recebido -> transcrição (speech-to-text) -> texto revisável -> mesmo endpoint/fluxo de conversa -> orquestrador e agentes`. O texto transcrito entra na mesma memória de sessão que uma mensagem digitada, com a origem registrada (`input_mode: audio`) e possibilidade de correção do usuário. Não criar um segundo orquestrador para áudio.

- Implementar um adaptador de transcrição independente do provedor (serviço/API de STT disponível no hackathon); configurar chave pelo ambiente, sem colocá-la no frontend ou no repositório.
- Caso STT não esteja configurado, retornar erro compreensível e **manter o chat por texto funcionando**.
- Exibir a transcrição para o cliente antes de operações que dependam de detalhes sensíveis a erro: valor, quantidade, alergias/restrições e confirmação de compra. Não executar pedido com base em áudio ambíguo.
- Definir limite razoável de duração/tamanho, validar tipo de arquivo e tratar falhas de transcrição.
- Não guardar áudio bruto por padrão; guardar somente o texto e metadados mínimos, quando permitido e necessário, respeitando privacidade e retenção.
- **MCP do iFood não transcreve áudio por definição.** Transcrição é responsabilidade da nossa aplicação, independentemente das ferramentas MCP de compra.

## 4. Agentes iniciais (papéis, não necessariamente modelos separados)

| Agente | Responsabilidade |
| --- | --- |
| **Orquestrador** | Distribui tarefas, consulta memória compartilhada, coordena interações e resolve conflitos entre propostas. |
| **Pesquisador** | Usa as ferramentas MCP para buscar restaurantes, produtos, ofertas e informações disponíveis. |
| **Planejador de compra** | Combina alternativas respeitando orçamento, preferências e restrições. |
| **Estrategista de vendas** | Avalia a abordagem de recomendação e personalização com base no contexto e, quando existirem, nos padrões de compra. |
| **Especialista em descontos** | **Propõe**, quando fizer sentido, um desconto ou promoção para melhorar o **lucro esperado**, avaliando impacto econômico e regras da empresa. |
| **Auditor** | Verifica consistência, restrições, qualidade dos dados e registra justificativas verificáveis para a gestão. |

Para o MVP, é aceitável reunir alguns desses papéis em poucas chamadas de IA e executar verificações simples por algoritmos tradicionais. **Não obrigar todos os agentes a participar de toda solicitação.**

### Escalabilidade: adicionar novos agentes sem reescrever o sistema

Projetar os agentes como módulos com um **contrato comum**, por exemplo:
- Identificador e nome do agente.
- Descrição da responsabilidade e critérios de acionamento.
- Ferramentas e permissões disponíveis.
- Entrada de tarefa estruturada e saída estruturada (resultado, justificativa, confiança/limitações quando aplicável).
- Capacidade de **ler o contexto compartilhado**, registrar resultados e emitir eventos no mesmo padrão.

O orquestrador deve descobrir/registrar especialistas por uma lista ou registro de agentes, sem depender de uma sequência fixa de `if/else` para cada agente novo. O frontend **não deve precisar de alterações específicas** para apresentar um novo agente: nome, papel, estado e comunicação vêm dos eventos emitidos pelo backend.

**Escalabilidade neste hackathon significa facilidade de extensão**, não infraestrutura distribuída de grande escala.

## 5. Memória compartilhada: todos trabalham com o mesmo contexto

Os agentes devem consultar um **estado compartilhado por atendimento** antes de tomar decisões e publicar nele suas descobertas relevantes. Isso evita que cada agente trabalhe com uma versão isolada do pedido.

Separar claramente:

1. **Memória operacional da sessão (fonte de verdade):** orçamento informado, preferências e restrições, produtos candidatos, carrinho atual, propostas, conflitos e status das tarefas. Dados estruturados e atualizados com controle de concorrência. Essa memória é usada diretamente para decidir o pedido.
2. **Memória persistente autorizada do cliente:** preferências e padrões de compra inferidos de histórico disponível e permitido, com origem, data e possibilidade de correção. Não presumir acesso ao histórico de compras via MCP.
3. **Conhecimento comercial compartilhado da empresa:** políticas, limites de desconto, estratégias documentadas e resultados anteriores aprovados para consulta por RAG (seção seguinte).
4. **Histórico/auditoria de eventos:** registrar mensagens entre agentes, ferramentas consultadas e decisões para visualização e investigação posterior.

**Memória não é garantia de ausência de erros.** Fatos críticos precisam ser validados; um agente não pode alterar silenciosamente uma restrição fornecida pelo cliente ou marcar uma proposta como compra concluída sem confirmação da ferramenta. Para o MVP, um armazenamento persistente simples (por exemplo, SQLite) já é suficiente; **não usar um único arquivo `.md` como estado concorrente de todos os agentes**.

## 6. RAG: o que recuperar e por quê

Implementar **RAG (Retrieval-Augmented Generation)** para recuperar conhecimento relevante antes de elaborar estratégias ou avaliar exceções. Fontes iniciais possíveis, mesmo que sejam documentos de demonstração:

- Regras e políticas comerciais da empresa, incluindo limites e condições de desconto.
- Descrições de produtos e dúvidas frequentes, quando a integração permitir.
- Estratégias de venda aprovadas e exemplos documentados de campanhas anteriores.
- Registros resumidos de decisões passadas e seus resultados **somente quando confiáveis e permitidos**.

Exemplo: o agente de descontos consulta pelo RAG a política comercial e casos anteriores relevantes **antes de sugerir uma promoção**. O agente deve indicar qual documento/regra fundamentou a sugestão. O RAG também pode ajudar o auditor a verificar se a proposta viola uma regra.

**Não usar RAG como substituto de ferramentas transacionais:** preço, disponibilidade, entrega, promoções atuais, carrinho e status de pedido devem vir das fontes atualizadas apropriadas, como APIs/ferramentas MCP. Uma regra/documento recuperado não pode sobrescrever o orçamento que o cliente acabou de informar.

Para a demo, um pequeno conjunto de documentos Markdown e recuperação simples já demonstra a ideia; embeddings e banco vetorial só se justificam se agregarem valor e houver tempo.

## 7. Padrões de compra e personalização

Quando existirem **dados disponíveis, uso autorizado e histórico suficiente**, o sistema deve identificar padrões que ajudem em próximas vendas, como:

- Categorias e pratos frequentemente comprados.
- Faixa de preço habitual, tamanho dos pedidos e preferências recorrentes.
- Horários/dias mais comuns de compra.
- Resposta observada a tipos de recomendação e promoções, sem confundir coincidência com causalidade.

Esses padrões podem atualizar a **memória persistente do cliente** e ser consultados pelos agentes em interações futuras, com data/origem e possibilidade de revisão. No MVP, começar com **regras e agregações simples** baseadas em compras de teste; não é necessário treinar outro modelo de IA. Se não houver histórico acessível, não fingir que existe: o chatbot pergunta preferências ou usa recomendações gerais.

O estrategista deve usar os padrões para **adaptar a apresentação e a seleção de ofertas**, não para inventar informações, fazer alegações enganosas ou ultrapassar o orçamento informado. O painel comercial pode apresentar tendências agregadas da operação quando houver dados.

## 8. Estratégia de venda, descontos e lucratividade

Os agentes podem comparar estratégias e propor abordagens diferentes para clientes diferentes. O **especialista em descontos** deve procurar oportunidades em que o incentivo melhore o **lucro esperado**, não apenas a taxa de conversão ou o número de pedidos.

Distinguir:
- **Receita:** valor cobrado na venda.
- **Custo/margem:** informações necessárias para avaliar rentabilidade, se fornecidas pela empresa.
- **Lucro esperado:** estimativa que considera a margem e a probabilidade de compra, deixando claras as hipóteses e incertezas.

Se faltarem custos, margens, elasticidade de demanda ou autorização comercial, o agente **não pode afirmar que calculou o desconto ótimo**: pode mostrar uma sugestão ilustrativa, pedir os dados ou testar regras pré-configuradas em modo de simulação. Só aplicar descontos reais quando uma ferramenta habilitada e as regras da empresa permitirem. Preferências e restrições do consumidor prevalecem sobre tentativas de aumentar lucro.

## 9. O que é MCP e como integrar com o iFood

**MCP (Model Context Protocol) não é um CRM, não é um agente de IA e não é, por si só, um sistema de vendas.** É um **protocolo padronizado** pelo qual uma aplicação de IA descobre e utiliza ferramentas e recursos disponibilizados por um **servidor MCP**. As ferramentas do servidor podem consultar APIs ou outros sistemas por trás. A **aplicação/agentes** decidem quando solicitar uma ferramenta; o **servidor MCP** executa a operação disponibilizada. O MCP não faz os agentes colaborarem automaticamente: a colaboração pertence ao nosso orquestrador.

**O que os vídeos fornecidos sobre o hackathon demonstram:**
- Cadastro/configuração de um agente/integração e suas credenciais no portal de desenvolvedores.
- Configuração do OpenCode para acessar ferramentas MCP do iFood.
- Um fluxo exemplificativo do lado do **comprador**, com descoberta de restaurantes/ofertas, recomendações, carrinho, envio de pedido e acompanhamento, conforme ferramentas habilitadas.

**Como usar no projeto:** nossa aplicação deve conectar-se aos **servidores/ferramentas MCP do iFood realmente liberados à equipe**, reutilizando busca, recomendações, carrinho e pedidos quando disponíveis. O OpenCode mostrado no tutorial é uma maneira de **testar e utilizar** ferramentas, não obriga que seja o chatbot final do produto. Confirmar lista de ferramentas, autenticação e permissões diretamente no ambiente antes de implementar.

**Não presumir**, sem validação, acesso a CRM, histórico completo de clientes, custos internos dos restaurantes, margens, estoque físico nem autorização para criar ou aplicar descontos. Para recursos comerciais indisponíveis, usar dados de empresa simulados ou informados explicitamente, sempre marcados como demonstração. **Nunca simular uma chamada como se fosse uma operação MCP real.** Não concluir compra/pagamento sem confirmação explícita do consumidor.

## 10. Integração com as interfaces — responsabilidade exclusiva do backend

**A equipe de design/frontend é separada e decidirá toda a experiência visual. Codex e Claude Code NÃO devem criar, alterar, desenhar, refatorar nem especificar layout, componentes visuais, navegação, identidade visual, animações ou CSS do chatbot ou do escritório.** Também não devem editar pastas/arquivos do frontend da outra equipe. Seu trabalho é **arquitetura + backend + interfaces de dados**. Não fazer mockups.

O backend precisa disponibilizar dados para dois consumidores independentes:

- **Chatbot do comprador:** sessão, mensagens de texto, transcrição de áudio, recomendações, carrinho e status de pedidos; o cliente nunca acessa dados internos do escritório nem de outros clientes.
- **Escritório da gestão comercial:** catálogo de agentes, estado por atendimento, comunicação **real entre agentes**, ações/ferramentas utilizadas, justificativas, propostas, alertas e métricas agregadas de operação. A representação visual pertence inteiramente à outra equipe.

**Forma de conexão fechada:** HTTP JSON para comandos, consultas e snapshots; **SSE** (`text/event-stream`) para eventos em tempo real; todos os payloads seguem estritamente a seção 15. Qualquer linguagem/framework do frontend consegue consumir esse contrato. O backend também deve oferecer histórico para reconexão e testes com dados de demonstração sinalizados. Não inventar outro formato/protocolo sem aprovação conjunta.

**Desacoplamento:** adicionar novos agentes altera apenas o registro e seus eventos no backend. Não exigir que a interface conheça classes Python ou nomes fixos de agentes. Cada evento deve ser persistido antes de ser transmitido, e o painel deve conseguir reconstruir o atendimento sem depender da conexão contínua.

## 11. Diferenciais a demonstrar

Preservar os seis problemas já escolhidos:

1. **Conflitos entre agentes:** comparar propostas incompatíveis e encaminhar a decisão para o orquestrador.
2. **Dados faltantes:** identificar lacunas, consultar fonte adequada ou perguntar ao cliente; não inventar dados.
3. **Explicabilidade:** mostrar mensagens, fontes, ferramentas e justificativas das decisões ao gestor comercial.
4. **Concorrência:** impedir que operações simultâneas comprometam o mesmo carrinho/estado da compra.
5. **Exceções:** verificar regras, restrições e autorizações antes de executar ações incomuns.
6. **Eficiência:** evitar ativar LLMs/agentes desnecessários para consultas simples e acompanhar custo/latência quando possível.

As novas capacidades de **memória compartilhada, RAG, identificação de padrões e extensibilidade** são os mecanismos de apoio que tornam esse escritório mais útil, não quatro produtos separados.

## 12. Escopo do MVP (~18 horas)

**Obrigatório para a primeira demonstração do produto como um todo** (Codex/Claude implementam **somente backend, contratos e testes**; outra equipe constrói e integra as telas):
- Backend compatível com o chatbot do comprador **por texto e áudio transcrito**; a interface conversacional será criada pela equipe de design/frontend.
- Ao menos uma consulta **MCP real** ao iFood, caso a integração seja liberada e funcione.
- Orquestrador que delega tarefas a especialistas com contrato comum.
- Pesquisa e recomendação de um pedido respeitando orçamento e preferências.
- Estado/memória compartilhada entre agentes **por atendimento**.
- **RAG mínimo** sobre regras/estratégias comerciais documentadas.
- **Pelo menos um exemplo** de padrão de compra influenciando uma recomendação, com histórico autorizado ou dados de demonstração declarados.
- Avaliação ilustrativa de estratégia de venda e proposta de desconto **sem alegar lucro real sem dados**.
- Eventos e endpoints que permitam ao painel do gestor comercial mostrar **comunicação entre agentes e eventos reais do backend**; a outra equipe decide como representar isso visualmente.
- Histórico e explicação verificável da decisão.
- Confirmação explícita antes de qualquer operação efetiva de compra.

**Somente se sobrar tempo:** várias rodadas de negociação autônoma; modelos de previsão avançados; aprendizado contínuo automatizado; métricas financeiras complexas; integrações adicionais; animações 3D; infraestrutura distribuída.


## 13. Instruções obrigatórias para Codex e Claude Code

1. Ler `PROMPT.md` integralmente e inspecionar o repositório; validar **quais ferramentas MCP do iFood existem de verdade**, em vez de presumir acesso a dados internos, desconto ou CRM.
2. **Trabalhar juntos na arquitetura do sistema inteiro** antes de dividir código: fluxo de sessões, serviços, responsabilidades, orquestração, memória, RAG, MCP, áudio, modelos de dados, autenticação/autorização, log de eventos e contrato HTTP/SSE/JSON. Não decidir arquiteturas incompatíveis em isolamento.
3. **Não tocar no design, frontend ou UX.** Todo trabalho visual é exclusivo de outra equipe. Não gerar interface provisória, exceto mocks estritamente de API necessários para testes do backend (sem UI).
4. Usar a seção 15 como **contrato v1 definitivo** do backend para as duas interfaces. Não renomear endpoints, chaves, estados ou tipos de evento unilateralmente. Se um requisito não couber no contrato, propor uma alteração de versão documentada e aguardar alinhamento; não lançar campos silenciosos.
5. Separar contexto operacional por atendimento, memória persistente por cliente, base de conhecimento RAG da empresa, métricas agregadas e eventos auditáveis. Um único banco compartilhado com isolamento por empresa/cliente é suficiente no MVP; **não criar um banco ou índice vetorial separado por cliente**.
6. Preferir algoritmos e regras para cálculos, ranking, restrições e estatísticas; usar LLM para linguagem, análise contextual e colaboração quando necessário. Não chamar todos os agentes para toda mensagem.
7. Verificar autorização por empresa e cliente no backend, não aceitar `tenant_id` arbitrário do navegador, não expor dados pessoais/descontos/credenciais em eventos e distinguir fonte real de demonstração.
8. Adotar transcrição de áudio (STT) como entrada no mesmo fluxo textual; não implementar TTS ou áudio em tempo real sem pedido.
9. Para o MVP, privilegiar fluxo de compra demonstrável, integração MCP testada, eventos persistidos e justificativas confiáveis. Sem ferramentas MCP, usar modo `demo` claramente marcado; jamais chamar dados simulados de dados reais.
10. Entregar código testável, documentação do contrato, exemplos JSON verificáveis e um script/teste de integração que simule sessão → mensagem → agentes → recomendação → aprovação de pedido.

## 14. Como Codex e Claude Code devem colaborar **na arquitetura e no backend**

**Ambos são responsáveis pela arquitetura. Nenhum deles é responsável por criar a interface.** Os agentes de programação não conversam automaticamente entre si: a colaboração ocorre por revisões documentadas, Git, contratos e integração progressiva.

### Fase A — projetar a arquitetura em conjunto (antes de implementar)

1. **Codex:** estuda o `PROMPT.md` e o repositório e propõe `docs/PROPOSTA_ARQUITETURA.md`: componentes, fluxo ponta a ponta, dados, MCP, sessões, contratos internos, risco das 18 horas e ordem de implementação. Sem escrever aplicação ainda.
2. **Claude Code:** lê o mesmo `PROMPT.md` e a proposta do Codex, faz uma **revisão crítica independente** em `docs/REVISAO_ARQUITETURA.md`: aponta falhas, acoplamentos, riscos, integrações difíceis, simplificações e melhorias. Não alterar frontend nem sobrescrever a proposta.
3. **Codex e Claude Code:** usando a proposta e a revisão, convergem em `docs/ARQUITETURA_FINAL.md`, inclusive fronteiras de módulos, responsabilidades e compatibilidade exata com a seção 15. O humano revisa/autoriza antes de implementar. Uma IA propõe e a outra revisa; ambas podem propor alterações, mas precisam concordar com os contratos.
4. **Congelar o contrato v1** da seção 15 para repassar à equipe de interface. Nenhuma equipe depende da implementação interna da outra.

### Fase B — implementar o **backend** em paralelo, depois da arquitetura aprovada

Divisão proposta, que pode ser ajustada **por acordo documentado**:

- **Codex:** infraestrutura do backend, sessão/autorização, API HTTP, SSE e log de eventos, adaptador MCP do iFood, fluxo do carrinho/pedido, adaptador STT de áudio e testes de integração dos endpoints.
- **Claude Code:** registro de agentes e orquestração, contexto/memória compartilhados, memória persistente de clientes, RAG, padrões de compra, estratégia comercial/descontos, auditoria de propostas e testes do domínio.
- **Integração conjunta:** definir antes os contratos Python/serviços internos, trabalhar em arquivos/pastas distintos, integrar frequentemente e fazer **revisão cruzada** dos testes. O Codex revisa a lógica multiagente; o Claude revisa as APIs/eventos e a correspondência com a seção 15.

Fluxo Git: um repositório, documentação versionada, branches/worktrees separados durante mudanças paralelas, commits pequenos, integração e testes em intervalos curtos; nunca editar simultaneamente o mesmo arquivo compartilhado. **Não atribuir frontend a qualquer uma das IAs.**

**Checkpoints obrigatórios:** (1) contrato e arquitetura aprovados; (2) criar sessão + enviar texto + observar SSE; (3) MCP real ou demo sinalizada; (4) agentes colaborando com memória/RAG; (5) áudio + recomendação + confirmação explícita; (6) entrega do contrato e amostras de payload à equipe responsável pelo design.

## 15. Contrato de integração v1 — JSON, endpoints, eventos e TODAS as chaves

Esta seção é a **fonte única de verdade para o formato de saída do backend**. Não define o design das interfaces; define exclusivamente o que elas recebem/enviam. Implementar, documentar e testar exatamente este contrato. Os exemplos JSON são válidos e a lista de chaves de cada objeto é **fechada**; não introduzir propriedades extras em v1. Propriedades explicitamente `null` continuam presentes.

### 15.1 Regras gerais (valem para TODOS os objetos)

- Prefixo HTTP: `/api/v1`; JSON em `snake_case`; UTF-8; datas em UTC ISO 8601 (`2026-10-17T18:00:00Z`); `schema_version` é o inteiro `1`.
- IDs são `string` estáveis e opacos; nunca derivar comportamento do formato do ID. `seq` é inteiro crescente e único **dentro de cada sessão**, não global. `event_id` é único globalmente.
- Dinheiro: **inteiros em centavos de BRL** (`3990` = R$ 39,90), nunca `float`; valores desconhecidos usam `null`. `discount_bps` é desconto percentual em pontos-base (`1000` = 10%).
- `mode`: `"real" | "demo"`. Em `demo`, integrações/dados simulados devem ser explicitamente identificados; resultados simulados não podem acionar pedidos reais.
- Estado de sessão: `"active" | "waiting_customer" | "closed" | "error"`. Estado de agente por sessão: `"idle" | "running" | "waiting" | "done" | "error"`.
- Todo objeto segue as chaves listadas abaixo, com o tipo indicado. Arrays vazios `[]` e valores nulos `null` são usados em vez de omitir campos. Campos `string` podem ser vazios **somente** onde explicitamente indicado; validação deve rejeitar entradas inadequadas.
- Transporte de autenticação para navegador: preferir **cookie de sessão `HttpOnly` e `Secure` em mesma origem** (ou proxy same-origin), permitindo SSE com `EventSource` sem expor tokens em URL; definir estratégia CSRF nos comandos HTTP. No ambiente local de demo, usar credenciais fictícias e manter perfis comprador/gestor separados. Não colocar tokens em query strings, eventos ou logs.
- Segurança: `tenant_id` e `client_id` devem ser verificados por autenticação/autorizações do backend. Nunca confiar em IDs enviados pelo cliente como prova de acesso. A interface do gestor comercial usa credencial de gestor; a do comprador usa credencial de comprador. Um gestor vê apenas empresas autorizadas e um comprador apenas sua sessão. O modo demo pode usar identidades fictícias isoladas.
- Toda resposta de **sucesso** tem formato exato definido adiante. Toda falha HTTP usa **um único** formato de erro comum. Uma operação aceita assincronamente pode emitir o resultado depois via SSE; `"accepted"` **não** é sinônimo de operação concluída.

### 15.2 Modelos compartilhados (estrutura exata)

**`AgentDefinition`** — cada elemento de `agents` no catálogo:

```json
{
  "agent_id": "researcher",
  "name": "Pesquisador",
  "role": "Busca de ofertas",
  "description": "Pesquisa produtos e restaurantes",
  "capabilities": ["offer_search"],
  "enabled": true
}
```

Tipos: `agent_id`, `name`, `role`, `description`: `string`; `capabilities`: `string[]`; `enabled`: `boolean`. Um agente novo aparece automaticamente via este catálogo, sem nova chave ou enum por agente.

**`AgentRuntime`** — estado do agente **nesta sessão**:

```json
{
  "agent_id": "researcher",
  "status": "running",
  "task_id": "task_1",
  "summary": "Pesquisando opções"
}
```

Tipos: `agent_id`: `string`; `status`: enum da seção 15.1; `task_id`: `string|null`; `summary`: `string|null`.

**`ChatMessage`** — mensagem exibível na conversa do comprador:

```json
{
  "message_id": "msg_001",
  "role": "customer",
  "input_mode": "audio",
  "text": "Quero jantar por até quarenta reais.",
  "created_at": "2026-10-17T18:00:00Z"
}
```

Tipos: `message_id`, `text`, `created_at`: `string`; `role`: `"customer" | "assistant"`; `input_mode`: `"text" | "audio"`. Uma resposta do assistente usa `input_mode: "text"`, mesmo se a entrada original veio de áudio.

**`CartItem`** — mesmo modelo para uma recomendação e para o carrinho:

```json
{
  "product_id": "prd_1",
  "name": "Hambúrguer",
  "quantity": 2,
  "unit_price_cents": 2990
}
```

Tipos: `product_id`, `name`: `string`; `quantity`: `integer > 0`; `unit_price_cents`: `integer >= 0`.

**`Recommendation`** — proposta estruturada para o chatbot e o gestor:

```json
{
  "recommendation_id": "rec_1",
  "merchant_id": "rest_1",
  "merchant_name": "Restaurante Exemplo",
  "items": [{"product_id":"prd_1","name":"Hambúrguer","quantity":2,"unit_price_cents":2990}],
  "currency": "BRL",
  "subtotal_cents": 5980,
  "delivery_fee_cents": 500,
  "other_fees_cents": 0,
  "discount_cents": 0,
  "total_cents": 6480,
  "eta_minutes": 35,
  "reasons": ["Dentro do orçamento"],
  "warnings": [],
  "data_origin": "ifood_mcp"
}
```

Tipos: `recommendation_id`, `merchant_id`, `merchant_name`: `string`; `items`: `CartItem[]`; `currency`: literal `"BRL"`; `subtotal_cents`, `delivery_fee_cents`, `other_fees_cents`, `total_cents`: `integer>=0|null`; `discount_cents`: `integer>=0`; `eta_minutes`: `integer>=0|null`; `reasons`, `warnings`: `string[]`; `data_origin`: `"ifood_mcp" | "demo"`. `total_cents` só é preenchido quando todos os valores necessários forem conhecidos, calculado como subtotal + entrega + outras taxas − descontos **efetivamente autorizados/aplicáveis**. Desconto apenas *sugerido* não entra no total.

**`Cart`** — snapshot do carrinho:

```json
{
  "cart_id": "cart_1",
  "status": "draft",
  "items": [{"product_id":"prd_1","name":"Hambúrguer","quantity":2,"unit_price_cents":2990}],
  "currency": "BRL",
  "total_cents": 6480,
  "data_origin": "ifood_mcp"
}
```

Tipos: `cart_id`: `string|null`; `status`: `"empty" | "draft" | "ready" | "submitted" | "error"`; `items`: `CartItem[]`; `currency`: literal `"BRL"`; `total_cents`: `integer>=0|null`; `data_origin`: `"ifood_mcp" | "demo"`.

### 15.3 HTTP — contratos completos de entrada e saída

**`POST /api/v1/sessions`** — cria um atendimento **antes** de iniciar tarefas ou assinar eventos.

Request JSON (todas as chaves):

```json
{"client_id":"client_demo_1"}
```

`client_id: string|null` (para atendimento anônimo); o backend valida se o identificador pertence ao comprador autenticado ou à conta de demonstração. Empresa/tenant é resolvida **pelo backend**, não pelo body.

Response `201`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_alias": "Cliente #1",
  "mode": "demo",
  "status": "active",
  "created_at": "2026-10-17T18:00:00Z"
}
```

Tipos: `schema_version: integer=1`, `session_id: string`, `client_alias: string`, `mode` e `status` conforme seção 15.1, `created_at: string(date-time)`.

**`POST /api/v1/audio/transcriptions`** — `multipart/form-data`, campos **exatamente** `audio` (arquivo binário) e `language` (string, valor `"pt-BR"`; opcional, padrão `"pt-BR"`). Não enviar áudio bruto para MCP do iFood.

Response `200`:

```json
{
  "schema_version": 1,
  "transcription_id": "tr_1",
  "text": "Quero hambúrguer sem cebola.",
  "language": "pt-BR",
  "requires_confirmation": true
}
```

Tipos: `transcription_id`, `text`, `language`: `string`; `requires_confirmation`: `boolean`. O texto retorna para **revisão do usuário**; a transcrição ainda **não** dispara agentes nem pedido. STT ausente retorna erro comum `STT_UNAVAILABLE` sem quebrar chat por texto.

**`POST /api/v1/chat/messages`** — envia mensagem de texto (digitada ou transcrita/confirmada) ao mesmo orquestrador.

Request JSON:

```json
{
  "session_id": "sess_1",
  "client_message_id": "msg_client_1",
  "text": "Quero hambúrguer sem cebola.",
  "input_mode": "audio",
  "transcription_id": "tr_1"
}
```

Tipos: `session_id`, `client_message_id`, `text`: `string` não vazia; `input_mode`: `"text" | "audio"`; `transcription_id`: `string|null` (`null` obrigatório para `text`, `string` válido para `audio`). `client_message_id` torna o envio **idempotente por sessão**: repetir a mesma solicitação não executa os agentes duas vezes.

Response `202` (aceito para processamento **assíncrono**; a resposta do chatbot chegará nos eventos):

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_message_id": "msg_client_1",
  "status": "accepted"
}
```

Tipos: `schema_version: integer=1`, `session_id`, `client_message_id`: `string`, `status`: literal `"accepted"`.

**`GET /api/v1/agents`** — catálogo para a gestão; não inclui posição visual nem layout.

Response `200`:

```json
{
  "schema_version": 1,
  "agents": [
    {"agent_id":"researcher","name":"Pesquisador","role":"Busca de ofertas","description":"Pesquisa produtos e restaurantes","capabilities":["offer_search"],"enabled":true}
  ]
}
```

Tipos: `schema_version: integer=1`, `agents: AgentDefinition[]`.

**`GET /api/v1/sessions/{session_id}/snapshot`** — estado completo recuperável ao abrir o painel ou reconectar.

Response `200`:

```json
{
  "schema_version": 1,
  "session": {
    "session_id": "sess_1",
    "client_alias": "Cliente #1",
    "status": "active",
    "mode": "demo",
    "created_at": "2026-10-17T18:00:00Z",
    "updated_at": "2026-10-17T18:01:00Z"
  },
  "last_seq": 3,
  "agents": [{"agent_id":"researcher","status":"running","task_id":"task_1","summary":"Pesquisando opções"}],
  "messages": [{"message_id":"msg_client_1","role":"customer","input_mode":"audio","text":"Quero hambúrguer sem cebola.","created_at":"2026-10-17T18:00:30Z"}],
  "recommendations": [],
  "cart": null
}
```

Tipos: `schema_version: integer=1`; `session: {session_id:string,client_alias:string,status:SessionStatus,mode:Mode,created_at:string,updated_at:string}`; `last_seq: integer>=0`; `agents: AgentRuntime[]`; `messages: ChatMessage[]`; `recommendations: Recommendation[]`; `cart: Cart|null`. O backend filtra os dados conforme o perfil autorizado; a mesma estrutura é mantida para ambos os públicos, podendo reduzir arrays privados conforme permissão **sem remover chaves**.

**`GET /api/v1/sessions/{session_id}/history?after_seq=3&limit=200`** — histórico ordenado para recuperação de eventos, autorizado e filtrado por audiência.

Response `200`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "events": [],
  "last_seq": 3,
  "has_more": false
}
```

Tipos: `schema_version: integer=1`, `session_id: string`, `events: OfficeEvent[]` (modelo abaixo), `last_seq: integer>=0` (último evento **devolvido**, ou `after_seq` quando a lista está vazia), `has_more: boolean`. O parâmetro `after_seq` é exclusivo; `limit` inteiro de 1 a 200. Eventos são devolvidos em `seq` crescente. O exemplo assume consulta sem novos eventos para essa audiência.

**`GET /api/v1/admin/overview`** — dados agregados da gestão, sem nomes ou dados pessoais; números indisponíveis são `null`, nunca inventados.

Response `200`:

```json
{
  "schema_version": 1,
  "mode": "demo",
  "window": {"from":"2026-10-17T00:00:00Z","to":"2026-10-18T00:00:00Z"},
  "metrics": {
    "sessions_started": 12,
    "messages_received": 31,
    "recommendations_made": 8,
    "orders_submitted": 3,
    "orders_confirmed": 1,
    "conversion_rate": null,
    "average_response_ms": 1200,
    "estimated_ai_cost_cents": null,
    "revenue_cents": null,
    "estimated_profit_cents": null
  },
  "recent_sessions": [
    {"session_id":"sess_1","client_alias":"Cliente #1","status":"active","updated_at":"2026-10-17T18:01:00Z","last_seq":3}
  ]
}
```

Tipos: `schema_version: integer=1`; `mode: Mode`; `window: {from:string(date-time), to:string(date-time)}`; `metrics` exatamente com as dez chaves acima: cinco contagens inteiras `>=0` (`sessions_started`, `messages_received`, `recommendations_made`, `orders_submitted`, `orders_confirmed`), `conversion_rate: number|null` entre 0 e 1 quando houver denominador e dados confiáveis, `average_response_ms: integer>=0|null`, `estimated_ai_cost_cents: integer>=0|null`, `revenue_cents: integer>=0|null`, `estimated_profit_cents: integer|null`; `recent_sessions: {session_id:string,client_alias:string,status:SessionStatus,updated_at:string,last_seq:integer}[]`. Todos os valores do exemplo são fictícios e `mode:"demo"` identifica isso.

**`POST /api/v1/orders/submit`** — **não** executa pagamento; tenta enviar um pedido **após** confirmação explícita e autorização.

Request JSON:

```json
{
  "session_id": "sess_1",
  "recommendation_id": "rec_1",
  "client_action_id": "action_1",
  "confirmed": true
}
```

Tipos: `session_id`, `recommendation_id`, `client_action_id`: `string` não vazia; `confirmed`: literal `true`. O backend valida recomendação, totais, permissões, idempotência (`client_action_id`) e dados oficiais de carrinho/checkout antes de executar. Em `mode:"demo"`, é somente simulação, sinalizada no evento de resultado.

Response `202`:

```json
{
  "schema_version": 1,
  "session_id": "sess_1",
  "client_action_id": "action_1",
  "status": "accepted"
}
```

Tipos: `schema_version: integer=1`, `session_id`, `client_action_id`: `string`; `status`: literal `"accepted"`. Pedido **não** é considerado enviado até evento oficial `order_status_changed`.

**`GET /api/v1/sessions/{session_id}/events?after_seq=0`** — SSE de eventos autorizados; cabeçalhos `Content-Type: text/event-stream`, cache desativado. Cada evento enviado nesse stream tem exatamente o formato abaixo:

```text
id: 4
event: office_event
data: {"schema_version":1,"event_id":"evt_4","seq":4,"occurred_at":"2026-10-17T18:02:00Z","tenant_id":"tenant_demo","session_id":"sess_1","type":"agent_message","actor":{"kind":"agent","id":"researcher"},"recipient":{"kind":"agent","id":"planner"},"visibility":"admin","mode":"demo","payload":{"message_id":"agent_msg_1","task_id":"task_1","channel":"proposal","summary":"Duas opções disponíveis dentro do orçamento."}}

```

`after_seq` e `Last-Event-ID` (quando enviado no reconnect) indicam a última sequência consumida: retornar apenas `seq` maior, em ordem. Usar `id: <seq>` e `event: office_event`. Heartbeats SSE podem ser comentários (`: keepalive`), sem JSON adicional. O cliente pode recuperar eventos perdidos pelo endpoint `/history`. A permissão filtra quais eventos são transmitidos ao comprador ou gestor.

### 15.4 `OfficeEvent` — envelope fixo para TODO evento

**Todas as chaves do envelope são obrigatórias**, inclusive `recipient` quando `null`:

```json
{
  "schema_version": 1,
  "event_id": "evt_4",
  "seq": 4,
  "occurred_at": "2026-10-17T18:02:00Z",
  "tenant_id": "tenant_demo",
  "session_id": "sess_1",
  "type": "agent_message",
  "actor": {"kind":"agent","id":"researcher"},
  "recipient": {"kind":"agent","id":"planner"},
  "visibility": "admin",
  "mode": "demo",
  "payload": {
    "message_id": "agent_msg_1",
    "task_id": "task_1",
    "channel": "proposal",
    "summary": "Duas opções disponíveis dentro do orçamento."
  }
}
```

Tipos: `schema_version: integer=1`, `event_id:string`, `seq:integer>=1`, `occurred_at:string(date-time)`, `tenant_id:string`, `session_id:string`, `type:EventType` (lista abaixo), `actor:Actor`, `recipient:Actor|null`, `visibility:"admin"|"customer"|"both"`, `mode:Mode`, `payload:EventPayload` (formato fechado por tipo). `Actor` tem **somente** as chaves `kind` (`"system" | "agent" | "customer" | "tool"`) e `id` (`string`). Não transmitir raciocínio interno dos modelos; só ações, mensagens operacionais resumidas e razões verificáveis.

**`type` permitidos e chaves EXATAS de `payload`** (a chave `payload` sempre contém o objeto indicado, sem campos extras):

| `type` | `payload` (nomes e tipos de todas as chaves) |
|---|---|
| `session_started` | `client_alias: string` |
| `chat_message` | `message: ChatMessage` |
| `agent_status` | `agent_id: string`, `status: AgentStatus`, `task_id: string|null`, `summary: string|null` |
| `agent_message` | `message_id: string`, `task_id: string`, `channel: "request"|"proposal"|"review"|"resolution"`, `summary: string` |
| `tool_activity` | `call_id: string`, `tool_name: string`, `provider: "ifood_mcp"|"internal"|"demo"`, `status: "started"|"succeeded"|"failed"`, `duration_ms: integer>=0|null`, `summary: string` |
| `knowledge_retrieved` | `query_id: string`, `topics: string[]`, `sources: {document_id:string,title:string}[]`, `count: integer>=0` |
| `memory_changed` | `scope: "session"|"customer"|"company"`, `keys: string[]`, `summary: string` |
| `pattern_identified` | `pattern_id: string`, `description: string`, `basis: "historical_orders"|"stated_preference"|"demo"`, `evidence_count: integer>=0`, `confidence: "low"|"medium"|"high"` |
| `discount_proposed` | `proposal_id: string`, `recommendation_id: string`, `discount_type: "percent"|"fixed"`, `discount_bps: integer>=0|null`, `discount_cents: integer>=0|null`, `estimated_profit_delta_cents: integer|null`, `status: "suggested"|"approved"|"rejected"`, `requires_approval: boolean`, `reason: string` |
| `conflict_detected` | `conflict_id: string`, `agent_ids: string[]`, `description: string`, `status: "open"|"resolved"` |
| `decision_made` | `decision_id: string`, `recommendation_id: string|null`, `summary: string`, `reasons: string[]`, `limitations: string[]` |
| `recommendations_ready` | `recommendations: Recommendation[]` |
| `cart_changed` | `cart: Cart` |
| `order_status_changed` | `order_id: string|null`, `status: "not_submitted"|"submitted"|"payment_pending"|"confirmed"|"failed"`, `summary: string` |
| `error` | `code: string`, `message: string`, `retryable: boolean` |
| `session_closed` | `outcome: "order_submitted"|"abandoned"|"closed"`, `summary: string` |

Regras para eventos: `actor/recipient` identificam emissor e destino **quando existirem**, sem depender de nomes fixos de agentes; `recipient:null` para eventos sem destino. `agent_message` deve ter `actor.kind="agent"` e `recipient.kind="agent"`; `chat_message` usa `role` e o ator coerentes; `discount_proposed` não significa desconto aplicado. **Eventos com `visibility:"admin"` jamais podem ser enviados a credenciais do consumidor.** Eventos `"both"` devem conter apenas informações adequadas aos dois públicos. Todos os eventos são armazenados por sessão para reconstrução e auditoria.

### 15.5 Erros HTTP e compatibilidade

Formato único de erro para **qualquer endpoint** (exemplo `400`, `401`, `403`, `404`, `409`, `422`, `429`, `503`):

```json
{
  "schema_version": 1,
  "request_id": "req_1",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "O orçamento informado precisa ser corrigido.",
    "retryable": false,
    "details": []
  }
}
```

Chaves exatas: `schema_version: integer=1`, `request_id:string`, `error:{code:string,message:string,retryable:boolean,details:string[]}`. Jamais retornar tokens, stack traces ou dados privados na mensagem de erro.

**Regras de implementação e aceite da integração com o time visual:**

1. Usar exatamente essas rotas, campos, tipos, enums e nulabilidade. Frontend **não precisa** saber como agentes, modelos, memória e MCP funcionam internamente.
2. Publicar documentação OpenAPI/JSON Schema ou modelos Pydantic **gerados e testados a partir deste contrato**, sem adicionar nova estrutura concorrente. Testes devem validar que os exemplos desta seção passam no parser e que não há campos faltantes ou extras nos DTOs.
3. Ao carregar a página de gestão, o cliente consegue consumir `/agents`, `/admin/overview` e `/sessions/{id}/snapshot`, e então reconectar `/events` com `after_seq` para não perder atividade.
4. O consumidor cria sessão, transcreve áudio se necessário, confirma/edita a transcrição, envia mensagem, recebe `202` e observa a resposta `chat_message` via SSE ou snapshot. Nunca presumir que `202` seja resposta final do agente.
5. As duas equipes devem usar uma coleção de respostas JSON de demonstração **compatíveis com este contrato**. Codex e Claude Code entregam os dados e testes; a outra equipe é livre para decidir toda a apresentação visual.
6. Alterações incompatíveis exigem versionamento explícito (`/api/v2`, `schema_version:2`) e alinhamento entre as equipes; **não quebrar v1 silenciosamente**.

**Resultado mínimo:** uma compra solicitada via texto ou áudio, especialistas trabalhando com estado compartilhado e acesso a ferramentas reais ou modo demo sinalizado, recomendação entregue ao chat e ações/mensagens dos agentes visíveis à interface comercial via JSON + SSE — **sem Codex ou Claude Code alterar qualquer tela**.
