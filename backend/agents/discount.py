"""Especialista em descontos: SUGERE (nunca aplica) um desconto quando, sob a política DEMO,
o lucro esperado melhora. Só atua em sessões demo; o total da recomendação não muda."""
from __future__ import annotations

from .commercial import DEMO_POLICY, expected_profit_delta
from .models import AgentResult, SessionContext, WorkingState
from .registry import AgentContext, AgentDefinition


def _best(state: WorkingState) -> dict | None:
    return next((r for r in state.recommendations if r["recommendation_id"] in state.approved_ids), None)


class DiscountSpecialist:
    definition = AgentDefinition(
        "discount_specialist", "Especialista em descontos", "Sugestão de incentivos",
        "Sugere descontos que melhoram o lucro esperado, conforme a política comercial",
        ["discount_suggestion"])
    order = 50

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        best = _best(state)
        return (session.mode == "demo" and best is not None
                and best["subtotal_cents"] >= DEMO_POLICY["min_subtotal_cents"])

    def run(self, ctx: AgentContext) -> AgentResult:
        best = _best(ctx.state)
        assert best is not None  # garantido por should_activate
        ctx.events.knowledge_retrieved("discount_specialist", ["desconto", "margem"],
                                       [{"document_id": DEMO_POLICY["document_id"],
                                         "title": DEMO_POLICY["title"]}])
        bps = DEMO_POLICY["discount_bps"]
        discount = min(best["subtotal_cents"] * bps // 10000, DEMO_POLICY["max_discount_cents"])
        delta = expected_profit_delta(best["subtotal_cents"], discount)
        if delta <= 0:
            return AgentResult("discount_specialist", "done", {"suggested": False},
                               "Pela política DEMO, um desconto não melhoraria o lucro esperado.", "low",
                               ["hipóteses de margem e conversão são de demonstração"])
        reason = (f"{DEMO_POLICY['title']}: {bps / 100:g}% em pedidos a partir de "
                  f"R$ {DEMO_POLICY['min_subtotal_cents'] // 100}. Hipóteses DEMO: margem 30%, "
                  "conversão 50%→65%. Sugestão ilustrativa, não aplicada.")
        ctx.events.discount_proposed("discount_specialist", best["recommendation_id"], bps, discount,
                                     delta, reason)
        return AgentResult("discount_specialist", "done", {"suggested": True, "discount_cents": discount},
                           "Desconto sugerido ao gestor (aguarda aprovação; não aplicado).", "low",
                           ["lucro estimado com hipóteses de demonstração, não com dados reais"])
