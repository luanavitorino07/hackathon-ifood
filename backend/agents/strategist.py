"""Estrategista de vendas: reordena as propostas JÁ aprovadas pela preferência do cliente.

Nunca altera preço, itens ou restrições; só a ordem de apresentação e as razões exibidas.
"""
from __future__ import annotations

import json
import re

from .ai import ask
from .commercial import DEMO_PURCHASE_HISTORY
from .customer_memory_agent import consult
from .models import AgentResult, SessionContext, WorkingState, slug
from .registry import AgentContext, AgentDefinition


def _matches(rec: dict, terms: list[str]) -> list[str]:
    haystack = slug(rec["merchant_name"] + " " + " ".join(i["name"] for i in rec["items"]))
    return [t for t in terms if slug(t) and slug(t) in haystack]


# Estratégias de venda (DEMO), espelhadas em backend/memory/knowledge/estrategias_venda_demo.md.
STRATEGIES = {
    "favorito": "Favorito do cliente",
    "custo_beneficio": "Melhor custo-benefício",
    "premium": "Experiência premium",
    "novidade": "Novidade no estilo do cliente",
    "saudavel": "Escolha leve e segura",
}
_STRATEGY_HELP = ("favorito = priorizar o que o cliente já pede ou declarou gostar; custo_beneficio = menor preço "
                  "por pessoa; premium = opção mais completa dentro do orçamento; novidade = algo novo parecido "
                  "com o gosto dele; saudavel = opção mais leve e mais segura para as restrições")

SYSTEM = ("Você é o Estrategista de vendas de um chatbot de comida. Escolha a estratégia de venda e a ordem de "
          "apresentação das opções (a primeira é a recomendação principal), usando o pedido, o histórico e o "
          "cadastro do cliente, o DESEMPENHO das estratégias (aceitas/oferecidas) e o documento aprovado. "
          f"Estratégias: {_STRATEGY_HELP}. Diga também se este cliente precisa de incentivo (desconto) para "
          "fechar, para o Especialista em descontos. Não invente preços, itens ou promoções; não use números no "
          "argumento. 'argumento': até 2 frases curtas e simpáticas para o cliente; 'motivo': por que essa "
          "estratégia e essa ordem, para o gestor, em até 2 frases.")
SCHEMA = {"type": "object", "required": ["ordem", "argumento", "motivo"],
          "properties": {
              "estrategia": {"type": "string", "enum": list(STRATEGIES)},
              "ordem": {"type": "array", "items": {"type": "string"}}, "argumento": {"type": "string"},
              "motivo": {"type": "string"}, "precisa_incentivo": {"type": "boolean"}}}


def performance_text(stats: list[tuple[str, int, int]] | tuple[tuple[str, int, int], ...]) -> str:
    """'Favorito do cliente 16/22; ...' (aceitas/oferecidas). Lido também pela Análise financeira."""
    return "; ".join(f"{STRATEGIES.get(k, k)} {a}/{n}" for k, n, a in stats if n)


class SalesStrategist:
    definition = AgentDefinition(
        "sales_strategist", "Estrategista de vendas", "Personalização da oferta",
        "Usa IA para escolher a ordem e o argumento de venda com base na memória do cliente e na estratégia",
        ["personalization"])
    order = 40

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return len(state.approved_ids) > 0 and not state.shopping_list

    def run(self, ctx: AgentContext) -> AgentResult:
        st, session = ctx.state, ctx.session
        facts = consult(ctx, "sales_strategist", "Quais as preferências e o histórico deste cliente?")
        if st.strategy_performance:  # a Memória também responde quais estratégias têm vendido
            ctx.events.agent_message("sales_strategist", "customer_memory", ctx.task_id, "request",
                                     "Quais estratégias de venda estão convertendo?")
            ctx.events.agent_message("customer_memory", "sales_strategist", ctx.task_id, "proposal",
                                     "Desempenho das estratégias: " + performance_text(st.strategy_performance))
            facts = {**facts, "desempenho_estrategias_geral": performance_text(st.strategy_performance)}
        terms, basis = self._patterns(ctx)
        approved = [r for r in st.recommendations if r["recommendation_id"] in st.approved_ids]
        favored = []  # reserva por regra: opções que citam a preferência/histórico
        for rec in approved:
            hits = _matches(rec, terms) if terms else []
            if hits:
                rec["reasons"].append("Combina com sua preferência: " + ", ".join(hits))
                favored.append(rec)
        strategy = self._strategy(ctx)
        if terms:  # padrões já identificados (declarados, histórico real ou DEMO) também vão para a IA
            facts = {**facts, "padroes_identificados": terms}
        decided = self._ask_ai(ctx, approved, facts, strategy)
        if decided is not None:
            order, why = decided
            st.recommendations = order + [r for r in st.recommendations if r not in order]
            self._brief_discount(ctx)
            return AgentResult("sales_strategist", "done", {"reordered": True, "by": "ia", "strategy": st.strategy},
                               f"Estratégia aplicada: {STRATEGIES[st.strategy or 'custo_beneficio']} — {why}"
                               + (f" (conforme \"{strategy[0]}\")" if strategy else ""), "medium")
        st.strategy = "favorito" if favored else "custo_beneficio"
        self._brief_discount(ctx)
        if not favored:
            return AgentResult("sales_strategist", "done", {"reordered": False, "strategy": st.strategy},
                               "Estratégia aplicada: Melhor custo-benefício — sem IA e sem preferência aplicável, "
                               "ordem por preço mantida.", "low")
        st.recommendations = favored + [r for r in st.recommendations if r not in favored]
        source = {"demo": "histórico DEMO"}.get(basis or "", "preferência declarada/pedidos anteriores")
        if strategy:
            source += f", conforme \"{strategy[0]}\""
        return AgentResult("sales_strategist", "done", {"reordered": True, "favored": len(favored), "by": "regra",
                                                       "strategy": st.strategy},
                           f"Estratégia aplicada: Favorito do cliente — {len(favored)} opção(ões) priorizada(s) "
                           f"por {source}.", "medium")

    @staticmethod
    def _brief_discount(ctx: AgentContext) -> None:
        """Passa ao Especialista em descontos a estratégia e se o cliente precisa de incentivo."""
        st = ctx.state
        if st.needs_incentive is None:  # sem IA: cliente sensível a preço quando a estratégia é preço
            st.needs_incentive = st.strategy == "custo_beneficio"
        opinion = "precisa de incentivo para fechar" if st.needs_incentive else "não precisa de desconto para fechar"
        ctx.events.agent_message("sales_strategist", "discount_specialist", ctx.task_id, "proposal",
                                 f"Vou de \"{STRATEGIES.get(st.strategy or '', st.strategy)}\"; "
                                 f"na minha leitura o cliente {opinion}.")

    @staticmethod
    def _patterns(ctx: AgentContext) -> tuple[list[str], str | None]:
        st, session = ctx.state, ctx.session
        terms: list[str] = []
        basis = None
        if st.constraints.preferences:
            terms += list(st.constraints.preferences)
            basis = "stated_preference"
            ctx.events.pattern_identified(
                "sales_strategist", "Preferência declarada: " + ", ".join(st.constraints.preferences),
                "stated_preference", len(st.constraints.preferences), "medium")
        profile = st.customer_profile
        if profile is not None and profile.favorite_dishes:  # histórico real de pedidos feitos ao bot
            dish, times = profile.favorite_dishes[0]
            terms += dish.split()
            basis = basis or "stated_preference"
            ctx.events.pattern_identified(
                "sales_strategist", f"Em atendimentos anteriores pediu {dish} ({times} vezes)",
                "stated_preference", times, "medium" if times >= 3 else "low")
        history = (DEMO_PURCHASE_HISTORY.get(session.client_id or "")
                   if session.mode == "demo" and not (profile and profile.favorite_dishes) else None)
        if history:
            terms += history["favorite_terms"]
            basis = basis or "demo"
            ctx.events.pattern_identified("sales_strategist", history["description"], "demo",
                                          history["orders"], "medium")
        return list(dict.fromkeys(slug(t) for t in terms if slug(t))), basis

    @staticmethod
    def _strategy(ctx: AgentContext) -> tuple[str, str] | None:
        """(título, trecho) da estratégia aprovada no RAG."""
        if ctx.knowledge is None:
            return None
        hits = ctx.knowledge.search(ctx.session.tenant_id, "personalização preferência histórico apresentação",
                                    ("personalização",), k=1)
        if not hits:
            return None
        ctx.events.knowledge_retrieved("sales_strategist", ["personalização"],
                                       [{"document_id": hits[0].document_id, "title": hits[0].title}])
        return hits[0].title, hits[0].excerpt

    @staticmethod
    def _ask_ai(ctx: AgentContext, approved: list[dict], facts: dict,
                strategy: tuple[str, str] | None) -> tuple[list[dict], str] | None:
        if len(approved) < 1:
            return None
        options = [{"id": r["recommendation_id"], "restaurante": r["merchant_name"],
                    "itens": [f"{i['quantity']}x {i['name']}" for i in r["items"]],
                    "total": None if r["total_cents"] is None else f"R$ {r['total_cents'] / 100:.2f}",
                    "avisos": r["warnings"]} for r in approved]
        prompt = (f"Pedido do cliente: {ctx.session.message_text}\n"
                  + (f"Pedido entendido: {ctx.state.request_summary}\n" if ctx.state.request_summary else "")
                  + f"CLIENTE_JSON: {json.dumps(facts, ensure_ascii=False)}\n"
                  f"ESTRATEGIA: {strategy[1] if strategy else 'sem documento'}\n"
                  f"OPCOES_JSON: {json.dumps(options, ensure_ascii=False)}")
        answer = ask(ctx, "sales_strategist", SYSTEM, prompt, SCHEMA)
        if answer is None:
            return None
        by_id = {r["recommendation_id"]: r for r in approved}
        order = [by_id[i] for i in dict.fromkeys(answer["ordem"]) if i in by_id]
        order += [r for r in approved if r not in order]
        pitch = answer["argumento"].strip()
        # o argumento não pode trazer números (preço/quantidade vêm do código, não da IA)
        if pitch and len(pitch) <= 220 and not re.search(r"\d|R\$", pitch):
            ctx.state.pitch = pitch
        why = answer["motivo"].strip()[:220] or "sem motivo informado"
        ctx.state.strategy = answer.get("estrategia") or "custo_beneficio"
        if isinstance(answer.get("precisa_incentivo"), bool):
            ctx.state.needs_incentive = answer["precisa_incentivo"]
        if order:
            order[0]["reasons"].append(f"Estratégia \"{STRATEGIES[ctx.state.strategy]}\": {why}")
        return order, why
