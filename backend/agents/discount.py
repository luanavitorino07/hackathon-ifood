"""Especialista em descontos: SUGERE (nunca aplica) um desconto quando, pela política comercial
recuperada no RAG, o lucro esperado melhora. Só atua em sessões demo; o total da recomendação não muda.

Sem base de conhecimento ligada, usa a política DEMO embutida (`commercial.DEMO_POLICY`) e diz isso.
"""
from __future__ import annotations

from dataclasses import dataclass

from .commercial import DEMO_POLICY, expected_profit_delta
from .models import AgentResult, SessionContext, WorkingState
from .registry import AgentContext, AgentDefinition

_REQUIRED = ("desconto_bps", "pedido_minimo_centavos", "teto_desconto_centavos", "margem_suposta_bps",
             "conversao_sem_desconto_bps", "conversao_com_desconto_bps")


@dataclass(frozen=True)
class _Policy:
    title: str
    discount_bps: int
    min_subtotal: int
    max_discount: int
    margin_bps: int
    conversion: tuple[int, int]
    sources: list[dict[str, str]]


def _best(state: WorkingState) -> dict | None:
    return next((r for r in state.recommendations if r["recommendation_id"] in state.approved_ids), None)


def _policy(ctx: AgentContext) -> _Policy | None:
    """Política do RAG; sem RAG, a embutida; com RAG mas sem política recuperada, None (não sugere)."""
    if ctx.knowledge is None:
        p = DEMO_POLICY
        return _Policy(f"{p['title']} (embutida)", p["discount_bps"], p["min_subtotal_cents"],
                       p["max_discount_cents"], p["assumed_margin_bps"], p["assumed_conversion_bps"],
                       [{"document_id": p["document_id"], "title": p["title"]}])
    hits = ctx.knowledge.search(ctx.session.tenant_id, "política de desconto margem pedido mínimo lucro esperado",
                                ("desconto",), k=3)
    sources = list({h.document_id: {"document_id": h.document_id, "title": h.title} for h in hits}.values())
    if sources:
        ctx.events.knowledge_retrieved("discount_specialist", ["desconto", "margem"], sources)
    params = next((h for h in hits if all(isinstance(h.data.get(k), int) for k in _REQUIRED)), None)
    if params is None:
        return None
    d = params.data
    return _Policy(params.title, d["desconto_bps"], d["pedido_minimo_centavos"], d["teto_desconto_centavos"],
                   d["margem_suposta_bps"], (d["conversao_sem_desconto_bps"], d["conversao_com_desconto_bps"]),
                   [{"document_id": params.document_id, "title": params.title}])


class DiscountSpecialist:
    definition = AgentDefinition(
        "discount_specialist", "Especialista em descontos", "Sugestão de incentivos",
        "Sugere descontos que melhoram o lucro esperado, conforme a política comercial",
        ["discount_suggestion"])
    order = 50

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return session.mode == "demo" and _best(state) is not None

    def run(self, ctx: AgentContext) -> AgentResult:
        best = _best(ctx.state)
        assert best is not None  # garantido por should_activate
        policy = _policy(ctx)
        if policy is None:
            return AgentResult("discount_specialist", "done", {"suggested": False},
                               "Nenhuma política de desconto recuperada; sem base para sugerir.", "low",
                               ["política comercial não encontrada na base de conhecimento"])
        if ctx.knowledge is None:
            ctx.events.knowledge_retrieved("discount_specialist", ["desconto", "margem"], policy.sources)
        if best["subtotal_cents"] < policy.min_subtotal:
            return AgentResult("discount_specialist", "done", {"suggested": False},
                               f"Abaixo do pedido mínimo da {policy.title}; sem sugestão.", "medium")
        discount = min(best["subtotal_cents"] * policy.discount_bps // 10000, policy.max_discount)
        delta = expected_profit_delta(best["subtotal_cents"], discount, policy.margin_bps, policy.conversion)
        if delta <= 0:
            return AgentResult("discount_specialist", "done", {"suggested": False},
                               f"Pela {policy.title}, um desconto não melhoraria o lucro esperado.", "low",
                               ["hipóteses de margem e conversão são de demonstração"])
        p0, p1 = policy.conversion
        reason = (f"{policy.title}: {policy.discount_bps / 100:g}% em pedidos a partir de "
                  f"R$ {policy.min_subtotal // 100}. Hipóteses do documento: margem {policy.margin_bps / 100:g}%, "
                  f"conversão {p0 / 100:g}%→{p1 / 100:g}%. Sugestão ilustrativa, não aplicada.")
        ctx.events.discount_proposed("discount_specialist", best["recommendation_id"], policy.discount_bps,
                                     discount, delta, reason)
        return AgentResult("discount_specialist", "done", {"suggested": True, "discount_cents": discount},
                           f"Desconto sugerido ao gestor com base em \"{policy.title}\" (aguarda aprovação).", "low",
                           ["lucro estimado com hipóteses de demonstração, não com dados reais"])
