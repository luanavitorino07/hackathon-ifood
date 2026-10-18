"""Estrategista de vendas: reordena as propostas JÁ aprovadas pela preferência do cliente.

Nunca altera preço, itens ou restrições; só a ordem de apresentação e as razões exibidas.
"""
from __future__ import annotations

from .commercial import DEMO_PURCHASE_HISTORY
from .models import AgentResult, SessionContext, WorkingState, slug
from .registry import AgentContext, AgentDefinition


def _matches(rec: dict, terms: list[str]) -> list[str]:
    haystack = slug(rec["merchant_name"] + " " + " ".join(i["name"] for i in rec["items"]))
    return [t for t in terms if slug(t) and slug(t) in haystack]


class SalesStrategist:
    definition = AgentDefinition(
        "sales_strategist", "Estrategista de vendas", "Personalização da oferta",
        "Ordena as opções aprovadas conforme preferências declaradas e padrões de compra",
        ["personalization"])
    order = 40

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return len(state.approved_ids) > 0

    def run(self, ctx: AgentContext) -> AgentResult:
        st, session = ctx.state, ctx.session
        terms: list[str] = []
        basis = None
        if st.constraints.preferences:
            terms += list(st.constraints.preferences)
            basis = "stated_preference"
            ctx.events.pattern_identified(
                "sales_strategist", "Preferência declarada: " + ", ".join(st.constraints.preferences),
                "stated_preference", len(st.constraints.preferences), "medium")
        history = DEMO_PURCHASE_HISTORY.get(session.client_id or "") if session.mode == "demo" else None
        if history:
            terms += history["favorite_terms"]
            basis = basis or "demo"
            ctx.events.pattern_identified("sales_strategist", history["description"], "demo",
                                          history["orders"], "medium")
        if not terms:
            return AgentResult("sales_strategist", "done", {"reordered": False},
                               "Sem preferências ou histórico: mantida a ordem por preço.", "low")
        terms = list(dict.fromkeys(slug(t) for t in terms if slug(t)))  # sem repetição
        approved = [r for r in st.recommendations if r["recommendation_id"] in st.approved_ids]
        favored = []
        for rec in approved:
            hits = _matches(rec, terms)
            if hits:
                rec["reasons"].append("Combina com sua preferência: " + ", ".join(hits))
                favored.append(rec)
        if not favored:
            return AgentResult("sales_strategist", "done", {"reordered": False},
                               "Nenhuma opção aprovada combina com as preferências; ordem por preço mantida.",
                               "low")
        rest = [r for r in st.recommendations if r not in favored]
        st.recommendations = favored + rest
        source = "histórico DEMO" if basis == "demo" else "preferência declarada"
        if ctx.knowledge is not None:  # fundamenta a personalização na estratégia aprovada (RAG)
            hits = ctx.knowledge.search(session.tenant_id, "personalização preferência histórico padrão de compra",
                                        ("personalização",), k=1)
            if hits:
                ctx.events.knowledge_retrieved("sales_strategist", ["personalização"],
                                               [{"document_id": hits[0].document_id, "title": hits[0].title}])
                source += f", conforme \"{hits[0].title}\""
        return AgentResult("sales_strategist", "done", {"reordered": True, "favored": len(favored)},
                           f"{len(favored)} opção(ões) priorizada(s) por {source}.", "medium")
