"""Especialista em descontos: SUGERE (nunca aplica) um desconto quando, pela política comercial
recuperada no RAG, o lucro esperado melhora. Só atua em sessões demo; o total da recomendação não muda.

Sem base de conhecimento ligada, usa a política DEMO embutida (`commercial.DEMO_POLICY`) e diz isso.
"""
from __future__ import annotations

from dataclasses import dataclass

import json

from .ai import ask
from .commercial import DEMO_POLICY, expected_profit_delta
from .customer_memory_agent import consult
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
    excerpt: str = ""


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
    excerpt = " ".join(h.excerpt for h in hits)[:900]
    return _Policy(params.title, d["desconto_bps"], d["pedido_minimo_centavos"], d["teto_desconto_centavos"],
                   d["margem_suposta_bps"], (d["conversao_sem_desconto_bps"], d["conversao_com_desconto_bps"]),
                   [{"document_id": params.document_id, "title": params.title}], excerpt)


SYSTEM = ("Você é o Especialista em descontos de um chatbot de comida. Decida se vale SUGERIR um desconto ao "
          "gestor para este pedido, seguindo a política comercial informada e o perfil do cliente. O desconto "
          "não pode passar do máximo da política e nunca é aplicado por você. Responda em português; 'motivo' "
          "em até 2 frases, citando a regra da política usada.")
SCHEMA = {"type": "object", "required": ["sugerir", "desconto_bps", "motivo"], "properties": {
    "sugerir": {"type": "boolean"}, "desconto_bps": {"type": "integer"}, "motivo": {"type": "string"}}}


class DiscountSpecialist:
    definition = AgentDefinition(
        "discount_specialist", "Especialista em descontos", "Sugestão de incentivos",
        "Sugere descontos que melhoram o lucro esperado, conforme a política comercial",
        ["discount_suggestion"])
    order = 50

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return session.mode == "demo" and _best(state) is not None

    @staticmethod
    def _decide_with_ai(ctx: AgentContext, best: dict, policy: _Policy, facts: dict) -> tuple[int, str]:
        """(bps, motivo). Sem IA: a regra da política (máximo permitido). A IA nunca passa do máximo."""
        prompt = (f"POLITICA: {policy.excerpt or policy.title}\n"
                  f"MAXIMO_BPS: {policy.discount_bps}; pedido mínimo: R$ {policy.min_subtotal / 100:.2f}\n"
                  f"PEDIDO: subtotal R$ {best['subtotal_cents'] / 100:.2f}, restaurante {best['merchant_name']}\n"
                  f"CLIENTE_JSON: {json.dumps(facts, ensure_ascii=False)}")
        answer = ask(ctx, "discount_specialist", SYSTEM, prompt, SCHEMA)
        if answer is None:
            return policy.discount_bps, ""
        if not answer["sugerir"]:
            return 0, answer["motivo"].strip()[:200] or "sem motivo informado"
        return max(0, min(answer["desconto_bps"], policy.discount_bps)), answer["motivo"].strip()[:200]

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
        facts = consult(ctx, "discount_specialist", "Esse cliente costuma pedir o quê e quanto gasta?")
        bps, ai_reason = self._decide_with_ai(ctx, best, policy, facts)
        if bps == 0:
            return AgentResult("discount_specialist", "done", {"suggested": False, "by": "ia"},
                               f"IA decidiu não sugerir desconto: {ai_reason}", "medium")
        discount = min(best["subtotal_cents"] * bps // 10000, policy.max_discount)
        delta = expected_profit_delta(best["subtotal_cents"], discount, policy.margin_bps, policy.conversion)
        if delta <= 0:
            return AgentResult("discount_specialist", "done", {"suggested": False},
                               f"Pela {policy.title}, um desconto não melhoraria o lucro esperado.", "low",
                               ["hipóteses de margem e conversão são de demonstração"])
        p0, p1 = policy.conversion
        reason = ((f"IA: {ai_reason} | " if ai_reason else "") + f"{policy.title}: até {policy.discount_bps / 100:g}% em pedidos a partir de "
                  f"R$ {policy.min_subtotal // 100}. Hipóteses do documento: margem {policy.margin_bps / 100:g}%, "
                  f"conversão {p0 / 100:g}%→{p1 / 100:g}%. Sugestão ilustrativa, não aplicada.")
        ctx.events.discount_proposed("discount_specialist", best["recommendation_id"], bps,
                                     discount, delta, reason)
        return AgentResult("discount_specialist", "done", {"suggested": True, "discount_cents": discount},
                           f"Desconto sugerido ao gestor com base em \"{policy.title}\" (aguarda aprovação).", "low",
                           ["lucro estimado com hipóteses de demonstração, não com dados reais"])
