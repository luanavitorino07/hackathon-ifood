# backend/memory — RAG mínimo e persistência do estado

Só biblioteca padrão. Testes: `python3 -m unittest discover -s backend/memory/tests -t .`

## Persistência por sessão — `SQLiteMemory` (implementa `MemoryPort`)

```python
from backend.memory import SQLiteMemory
memory = SQLiteMemory("backend_state.db")   # ou ":memory:" em testes
```

Semântica (acordada com o módulo de agentes): sessão desconhecida → `state={}`, `revision=0`; o patch
substitui chaves de topo, sem merge profundo; `None` grava `null`; revisão divergente levanta
`RevisionConflict` (de `backend.agents.ports`) e não grava nada; cada gravação incrementa a revisão em 1;
comparação, gravação e auditoria são atômicas (`BEGIN IMMEDIATE` + lock); `load` devolve cópia
independente; valores precisam ser serializáveis em JSON. `audit(session_id)` lista quem gravou quais
chaves em cada revisão, sem os valores.

Para usar na API: `build_application(memory=SQLiteMemory("..."))` (composição em `backend/api/main.py`).
O arquivo `.db` não deve ser versionado.

## Memória do cliente — `SQLiteCustomerMemory` (implementa `CustomerMemoryPort`)

Pedidos feitos ao bot em cada atendimento, por `(tenant_id, client_id)`: só prato, quantidade, orçamento,
atendimento e data — sem nome, contato ou endereço. **Não são compras confirmadas** (o bot não vê a compra).
`profile()` calcula atendimentos, pratos favoritos (2+ atendimentos), último pedido e orçamento típico por
pessoa (mediana). `forget()` apaga o histórico do cliente. Os agentes usam a instância padrão
`default_customer_memory()` (uma por processo, em memória: vale enquanto a API estiver no ar); para
persistir em arquivo, passe `SQLiteCustomerMemory("<arquivo>.db")` em `build_orchestrator(customers=...)`.

## Conhecimento comercial (RAG) — `MarkdownKnowledgeBase` (implementa `KnowledgePort`)

Documentos em `knowledge/*.md` (todos de DEMONSTRAÇÃO). Cada seção `## ...` vira um trecho buscável;
uma seção pode ter `topics: a, b` e um bloco ` ```params ` com `chave: valor`, devolvido em
`KnowledgeHit.data`. Busca por palavras-chave com peso por raridade (idf) e bônus por tópico; sem banco
vetorial. Os agentes usam a base padrão automaticamente (`backend.agents.bootstrap.default_knowledge`).

- `politica_comercial_demo.md`: quando sugerir desconto e os parâmetros que o especialista em descontos usa.
- `estrategias_venda_demo.md`: personalização, apresentação e restrições alimentares.

Para mudar a política de desconto da demo, edite o bloco `params` do documento — não o código.
Documentos não substituem dados transacionais: preço, disponibilidade e taxas vêm do iFood.
