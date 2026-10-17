# AGENTS.md — Regras de colaboração do hackathon iFood

## Fonte de verdade
- Leia `PROMPT.md` antes de implementar qualquer coisa. Ele descreve o produto e o contrato JSON com a equipe de interface.
- Este arquivo governa **como** trabalhar; `PROMPT.md` governa **o que** construir.
- Não alterar design, frontend ou telas. Essas partes pertencem a outra equipe.

## Responsabilidades e limites de edição
As pastas abaixo são limites de propriedade. Crie somente sua pasta, caso não exista.

| Branch | Responsável | Pode criar/editar | Não editar |
| --- | --- | --- | --- |
| `feat/agents` | Claude Code | `backend/agents/**` | `backend/memory/**`, `backend/integrations/**`, `backend/api/**`, frontend |
| `feat/memory` | Codex local | `backend/memory/**` | `backend/agents/**`, `backend/integrations/**`, `backend/api/**`, frontend |
| `feat/integrations` | Codex do colega | `backend/integrations/**`, `backend/api/**` | `backend/agents/**`, `backend/memory/**`, frontend |

Arquivos compartilhados (`PROMPT.md`, `AGENTS.md`, `CLAUDE.md`, `docs/**`, arquivos na raiz, dependências, configurações, infraestrutura, schemas comuns) só podem ser modificados após acordo explícito entre os responsáveis, coordenado por uma pessoa da equipe. Se precisar alterar um deles: **pare, proponha a mudança por escrito e aguarde autorização**.

## Contratos entre módulos
- Trate o contrato de API/eventos do `PROMPT.md` como estável. Não renomeie campos JSON, tipos de eventos ou endpoints unilateralmente.
- Se precisar de um contrato Python compartilhado, primeiro proponha interface, tipos, assinaturas, exemplos de payload e quem será dono do arquivo; só implemente depois do acordo.
- Não invente ferramentas ou permissões MCP do iFood. Se estiver indisponível, use adaptadores de teste claramente identificados, sem alegar integração real.
- Toda comunicação entre agentes que precisar aparecer na interface deve emitir eventos estruturados pelo contrato estabelecido.
- Não ler ou divulgar credenciais, dados pessoais ou tokens em logs, commits ou mensagens. Usar variáveis de ambiente e exemplos sem segredos.

## Procedimento obrigatório em toda tarefa
1. Mostre a branch atual (`git branch --show-current`) e confira que corresponde ao seu módulo.
2. Leia `PROMPT.md` e este arquivo; no Claude Code, leia também `CLAUDE.md`.
3. Declare quais arquivos pretende alterar. **Não escreva fora da sua área sem autorização humana.**
4. Implemente em mudanças pequenas, com testes e commits descritivos na **sua branch**.
5. Antes de concluir, apresente lista de arquivos alterados, testes executados, pendências e mudanças de contrato propostas.
6. Faça `git push` somente para a sua branch. Não fazer merge, rebase, cherry-pick ou push em `main` sem orientação explícita.

## Integração e segurança do trabalho
- Não executar `git reset --hard`, `git clean -fd`, `git push --force` nem apagar worktrees/branches sem autorização explícita.
- Não modificar, formatar em massa, mover ou apagar arquivos de outros módulos.
- Se surgir erro em módulo de outra pessoa, reporte o erro e proponha correção; não edite por conta própria.
- Cada desenvolvedor trabalha na própria branch/worktree. Integrações para `main` são revisadas por humano via Pull Request.
- Antes de aprovar um PR, revisar o diff, verificar que não há mudanças fora da área autorizada e rodar os testes adequados.

## Prioridades do hackathon
Primeiro entregar um fluxo mínimo de ponta a ponta: mensagem do cliente → agentes → integração iFood (ou simulação declarada) → resposta JSON e eventos para interface. Depois ampliar memória, RAG, análise de padrões e estratégias comerciais. Não construir funcionalidades extras não solicitadas.
