# Arquitetura do Escritório Virtual Multiagente — iFood

> Texto para o documento final (PDF), focado nos agentes. A arquitetura inteira (frontend, API, integrações,
> memória, contrato, execução e testes) está em `docs/ARQUITETURA_COMPLETA.md`.

## 1. Visão geral

O produto é um **chatbot vendedor** que atende o cliente por texto ou áudio. Por trás dele, um
**escritório virtual de agentes de IA** pesquisa no iFood, monta propostas, confere tudo e decide como
apresentar a oferta. O gestor comercial acompanha esse escritório em tempo real: vê cada agente, as
mensagens entre eles, os conflitos e as justificativas. O cliente só vê o chat e as recomendações.

O sistema atende dois tipos de compra:

- **Comida de restaurante**: "pizza para 4 pessoas até R$ 120, uma opção vegetariana".
- **Compra de supermercado, na hora ou agendada**: "compra do mês no mercado: arroz 5 kg, 2 feijões,
  leite e café", ou "mercado todo sábado às 10h: ...".

```
Cliente (texto/áudio)
      │  áudio → transcrição local (Whisper) → texto revisado pelo cliente
      ▼
API HTTP + SSE  ──────────────►  Escritório do gestor (eventos em tempo real)
      │
      ▼
Orquestrador ── Intérprete (IA) ── Memória do cliente
      │
      ├─ Comida:   Pesquisador → Curador (IA) → Planejador → Auditor → Estrategista (IA) → Descontos (IA)
      └─ Mercado:  Pesquisador → Montador da cesta (IA) → Auditor → Descontos (IA) → agendamento
      │
      ▼
Resposta ao cliente (o pedido só avança com confirmação explícita)
```

**Princípio central: a IA entende e julga; o código calcula e garante.** Preço, total, orçamento,
restrição alimentar e origem dos dados nunca são decididos só pela IA. Toda resposta da IA é validada
contra um formato fixo. Se a IA falhar (cota, demora ou resposta fora do formato), cada agente usa uma
regra de reserva e o atendimento continua.

## 2. Os agentes

O sistema tem **10 agentes**. Eles ficam num registro e são escolhidos a cada etapa conforme o
estado do atendimento. O fluxo não é uma sequência fixa: perguntas simples ("oi", "obrigado") não
acionam a pesquisa nem gastam IA. Um agente novo entra só pelo registro e aparece sozinho no painel
do gestor, sem mudança no frontend.

### Orquestrador (coordenação, com IA)
Recebe cada mensagem, consulta a memória do atendimento e decide quais especialistas acionar. Ele:

- resolve os conflitos entre agentes e registra a decisão com justificativa;
- reescreve a resposta final de forma natural, com IA. O guarda-corpo é rígido: a resposta só vale se
  citar o restaurante e o total exatos, sem outros valores, e mantiver todos os avisos;
- cuida do **agendamento das compras de mercado**, por regra e sem IA. O horário precisa ter pelo menos
  30 minutos e no máximo 4 meses de antecedência. O agendamento só vale depois que o cliente confirma.
  Na data, a cesta é refeita com os preços do dia e o cliente confirma de novo.

### Intérprete (entendimento do pedido, com IA)
Entende a mensagem usando o contexto da conversa:

- o prato, ou a lista de mercado, com quantidades e tamanhos ("arroz 5 kg", "2 leites");
- quantas pessoas ("eu e 3 amigos" = 4) e o orçamento;
- as restrições, inclusive de só parte do grupo ("um amigo é vegano") ou só de um item
  ("leite sem lactose" vale só para o leite);
- as preferências ("um poke já montado");
- a data e a recorrência ("amanhã", "sábado", "toda semana", "todo mês");
- se a mensagem é um pedido, um ajuste, uma confirmação ("fechado") ou só conversa.

Guarda-corpos: valores escritos pelo cliente ("R$ 80", "4 pessoas", "supermercado") valem mais que a
leitura da IA, e a IA nunca retira uma restrição sozinha. Só o cliente retira, de forma explícita
("não sou vegano, errei").

### Memória do cliente (histórico e preferências)
Responde aos outros agentes com o histórico autorizado do cliente: pedidos anteriores, restrições e
preferências do cadastro e quais estratégias de venda funcionaram com ele. Sempre informa de onde veio
cada dado. Permite "quero o mesmo da última vez". Sem histórico, ela diz isso; nunca inventa.

### Pesquisador (busca no iFood)
É o único agente que consulta o iFood, pela ferramenta MCP `searchOffers`.

- **Comida:** busca o prato e, se o cliente pediu, cada complemento ("com coca e batata frita"). O que faltar
  num restaurante do prato é procurado **dentro** desse restaurante, para o pedido sair de uma loja só.
- **Mercado:** faz uma busca por item da lista em supermercados. Depois procura os itens que faltaram
  **dentro do mercado que mais cobriu a lista**, para a cesta sair de uma loja só, com uma entrega.

Um resultado só é marcado como dado real do iFood se houver prova de uma chamada MCP bem-sucedida.

### Curador (julgamento de relevância, com IA; só comida)
Julga, item por item, se o que o iFood devolveu é o que o cliente pediu. Exemplo: "pastel de pizza"
não é pizza. Também informa quantas pessoas cada item serve e quais restrições o item atende ou
contraria. Se nada serve, pede ao Pesquisador outra busca com um termo melhor; isso fica registrado
como conflito Curador × Pesquisador. Ele só julga itens que vieram da busca: nunca cria item nem preço.

### Planejador de compra (regras; só comida)
Monta as combinações por algoritmo, sem IA: quantidade suficiente para o grupo, orçamento respeitado,
pelo menos uma opção vegetariana quando pedida, complementos no mesmo restaurante e lojas fechadas
descartadas. Calcula subtotal, taxas e total em centavos.

### Montador da cesta (cesta de supermercado, com IA; só mercado)
Para cada mercado encontrado:

- a IA escolhe o produto de cada item da lista ("doce de leite" não é "leite") e a quantidade pelo
  tamanho pedido ("5 kg" com pacote de 1 kg = 5 pacotes);
- a IA indica quais restrições cada produto contraria;
- o código monta a cesta (um mercado por proposta), soma o total, respeita o orçamento e avisa o que
  não foi encontrado naquele mercado.

As cestas são ordenadas pela quantidade de itens da lista que cobrem e depois pelo preço. Numa compra
agendada, o mercado escolhido antes tem preferência.

### Auditor (verificação, regras)
Confere cada proposta antes de o cliente vê-la, de forma independente:

- o item veio da busca e o preço é o mesmo da busca;
- o total está certo e cabe no orçamento;
- o restaurante ou mercado está aberto;
- a quantidade atende o grupo;
- cada produto da cesta corresponde a um item da lista;
- toda restrição tem prova (etiqueta do iFood) ou avaliação da IA com aviso ao cliente;
- não há desconto aplicado sem autorização.

Proposta reprovada volta ao autor com o motivo (conflito Planejador × Auditor ou Montador × Auditor).

### Estrategista de vendas (personalização, com IA; só comida)
Antes de decidir, pergunta à Memória do cliente quais estratégias costumam converter. Escolhe uma
estratégia nomeada (`favorito`, `custo_beneficio`, `premium`, `novidade` ou `saudavel`), a ordem das
opções aprovadas e o argumento de venda. Ele nunca muda preço, item ou restrição. Também diz ao
Especialista em descontos se o cliente parece precisar de incentivo. Quando o cliente fecha a compra,
a venda é atribuída à estratégia; esse é o dado da monitoria de estratégias na Análise financeira.

### Especialista em descontos (sugestão de incentivo, com IA)
Antes de sugerir, consulta pelo RAG a política comercial da empresa e cita o documento usado. A IA
decide se sugere desconto e de quanto, nunca acima do teto da política; o lucro esperado é calculado
pelo código. A sugestão vai **só para o gestor**, marcada como pendente de aprovação. Não entra no
preço nem na fala ao cliente. Se discordar do Estrategista, o orquestrador resolve o conflito.
Margens e elasticidade são hipóteses de demonstração, sinalizadas como tal.

## 3. Comunicação e conflitos

Os agentes conversam entre si, e não só com o orquestrador: o Curador pede nova busca ao Pesquisador,
o Planejador pede conferência ao Auditor, o Estrategista consulta a Memória. Cada mensagem vira um
evento estruturado (pedido, proposta, revisão ou resolução), que é **gravado antes de ser
transmitido** ao painel do gestor. O cliente nunca recebe eventos internos.

Conflitos reais registrados e resolvidos:

- **Curador × Pesquisador:** nada do que veio serve; o Curador pede outra busca.
- **Planejador (ou Montador) × Auditor:** proposta reprovada e descartada.
- **Orçamento × pedido:** não cabe no orçamento; fica aberto até o cliente responder.
- **Estrategista × Descontos:** opiniões diferentes sobre dar incentivo.
- **Pedido × cadastro:** dieta por escolha cede ao pedido explícito; restrição de saúde nunca cede.

## 4. Memória, RAG e dados

- **Memória do atendimento** (SQLite): orçamento, restrições, lista de compras, propostas e auditoria.
  Tem controle de concorrência, e mensagens da mesma sessão são processadas uma por vez.
- **Memória do cliente:** histórico de pedidos ao bot e resultado das estratégias, com origem e data.
- **RAG comercial:** documentos de política e estratégia (demonstração) consultados antes de sugerir
  desconto. O RAG nunca substitui o iFood: preço e disponibilidade vêm sempre da busca atual.
- **Agendamentos:** guardados no processo da API. Um relógio verifica a cada 30 s quais chegaram na
  data e manda refazer a cesta.
- **Eficiência:** se só mudou o orçamento ou o número de pessoas, a pesquisa dos últimos 5 minutos é
  reaproveitada. Conversa simples não aciona a esteira. Uma compra de comida faz de 5 a 7 chamadas de
  IA (Claude Haiku), em cerca de 10 a 30 segundos.

## 5. Integração e limites honestos

- **iFood MCP real:** a credencial liberada só permite **busca** (`searchOffers`, em restaurantes e
  supermercados). Não há ferramenta de carrinho, pedido, pagamento ou agendamento. Por isso nenhuma
  compra é enviada ao iFood: a confirmação do cliente fica registrada e o envio é indicado como simulado.
- **Agendamento:** fica no nosso sistema. Na data, o bot refaz a cesta com os preços do dia e pede
  confirmação. Ele nunca compra sozinho.
- **Áudio:** transcrição local com Whisper; o cliente revisa o texto antes de enviar.
- **Modo demonstração:** catálogo e IA simulados, sempre marcados como demonstração; dado simulado
  nunca é apresentado como real.
- **Pendências para produção:** guardar agendamentos e histórico em banco persistente, autenticação real
  e envio de pedido e pagamento quando o iFood liberar essas ferramentas.
