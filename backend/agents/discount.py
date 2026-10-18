"""Especialista em descontos: SUGERE (nunca aplica) um desconto quando, pela política comercial
recuperada no RAG, o lucro esperado melhora. O total da recomendação não muda; a sugestão vai ao gestor.
Ouve o Estrategista (o cliente precisa de incentivo?) e, quando discordam, o conflito vai ao escritório.

Sem base de conhecimento ligada, usa a política DEMO embutida (`commercial.DEMO_POLICY`) e diz isso.
"""
from __future__ import annotations

from dataclasses import dataclass

import json

from .ai import ask
from .commercial import DEMO_POLICY, expected_profit_delta
from .customer_memory_agent import consult
from .events import ORCHESTRATOR_ID, new_id
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
          "não pode passar do máximo da política e nunca é aplicado por você. Considere a opinião do Estrategista "
          "de vendas, mas decida pela política e pelo lucro esperado. As hipóteses de margem e conversão da "
          "política (DEMO) são as aprovadas para esta demonstração: use o LUCRO_ESPERADO informado, sem exigir "
          "outros dados. Responda em português; 'motivo' em até 2 frases, citando a regra da política usada.")
SCHEMA = {"type": "object", "required": ["sugerir", "desconto_bps", "motivo"], "properties": {
    "sugerir": {"type": "boolean"}, "desconto_bps": {"type": "integer"}, "motivo": {"type": "string"}}}


def _opinion(st: WorkingState) -> str:
    return {True: "precisa de incentivo", False: "não precisa de desconto"}.get(st.needs_incentive, "sem opinião")


def _close(ctx: AgentContext, result: AgentResult) -> AgentResult:
    """Responde ao Estrategista; se discordarem, registra e resolve o conflito (a sugestão nunca é aplicada)."""
    st, suggested = ctx.state, bool(result.output.get("suggested"))
    ctx.events.agent_message("discount_specialist", "sales_strategist", ctx.task_id, "review",
                             result.justification)
    if st.needs_incentive is None or st.needs_incentive == suggested:
        return result
    cid = new_id("conf")
    if suggested:
        desc = "Estrategista: cliente não precisa de desconto; Especialista em descontos: sugerir desconto pela política"
        how = "Sugestão vai ao gestor com a ressalva do Estrategista; nada é aplicado ao cliente"
    else:
        desc = "Estrategista pediu incentivo; Especialista em descontos: a política comercial não permite neste pedido"
        how = "Vale a política comercial: sem desconto neste pedido"
    ctx.events.conflict(cid, ["sales_strategist", "discount_specialist"], desc, "open")
    ctx.events.agent_message(ORCHESTRATOR_ID, "discount_specialist", cid, "resolution", how)
    ctx.events.conflict(cid, ["sales_strategist", "discount_specialist"], how, "resolved")
    return result


class DiscountSpecialist:
    definition = AgentDefinition(
        "discount_specialist", "Especialista em descontos", "Sugestão de incentivos",
        "Sugere descontos que melhoram o lucro esperado, conforme a política comercial",
        ["discount_suggestion"])
    order = 50

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return _best(state) is not None

    @staticmethod
    def _decide_with_ai(ctx: AgentContext, best: dict, policy: _Policy, facts: dict) -> tuple[int, str]:
        """(bps, motivo). Sem IA: a regra da política (máximo permitido). A IA nunca passa do máximo."""
        top = min(best["subtotal_cents"] * policy.discount_bps // 10000, policy.max_discount)
        gain = expected_profit_delta(best["subtotal_cents"], top, policy.margin_bps, policy.conversion)
        prompt = (f"POLITICA: {policy.excerpt or policy.title}\n"
                  f"LUCRO_ESPERADO: com o desconto máximo (R$ {top / 100:.2f}) a variação esperada do lucro é "
                  f"R$ {gain / 100:+.2f} por pedido (hipóteses DEMO da política)\n"
                  f"MAXIMO_BPS: {policy.discount_bps}; pedido mínimo: R$ {policy.min_subtotal / 100:.2f}\n"
                  f"PEDIDO: subtotal R$ {best['subtotal_cents'] / 100:.2f}, restaurante {best['merchant_name']}\n"
                  f"CLIENTE_JSON: {json.dumps(facts, ensure_ascii=False)}\n"
                  f"OPINIAO_DO_ESTRATEGISTA: cliente {_opinion(ctx.state)}")
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
            return _close(ctx, AgentResult("discount_specialist", "done", {"suggested": False},
                               "Nenhuma política de desconto recuperada; sem base para sugerir.", "low",
                               ["política comercial não encontrada na base de conhecimento"]))
        if ctx.knowledge is None:
            ctx.events.knowledge_retrieved("discount_specialist", ["desconto", "margem"], policy.sources)
        if best["subtotal_cents"] < policy.min_subtotal:
            return _close(ctx, AgentResult("discount_specialist", "done", {"suggested": False},
                               f"Abaixo do pedido mínimo da {policy.title}; sem sugestão.", "medium"))
        facts = consult(ctx, "discount_specialist", "Esse cliente costuma pedir o quê e quanto gasta?")
        bps, ai_reason = self._decide_with_ai(ctx, best, policy, facts)
        if bps == 0:
            return _close(ctx, AgentResult("discount_specialist", "done", {"suggested": False, "by": "ia"},
                               f"IA decidiu não sugerir desconto: {ai_reason}", "medium"))
        discount = min(best["subtotal_cents"] * bps // 10000, policy.max_discount)
        if ctx.session.mode == "real":  # sem margem real da empresa: hipóteses da política DEMO, só ilustrativas
            ai_reason = (ai_reason + " " if ai_reason else "") + "(atendimento real; margem e conversão são hipóteses DEMO)"
        delta = expected_profit_delta(best["subtotal_cents"], discount, policy.margin_bps, policy.conversion)
        if delta <= 0:
            return _close(ctx, AgentResult("discount_specialist", "done", {"suggested": False},
                               f"Pela {policy.title}, um desconto não melhoraria o lucro esperado.", "low",
                               ["hipóteses de margem e conversão são de demonstração"]))
        p0, p1 = policy.conversion
        reason = ((f"IA: {ai_reason} | " if ai_reason else "") + f"{policy.title}: até {policy.discount_bps / 100:g}% em pedidos a partir de "
                  f"R$ {policy.min_subtotal // 100}. Hipóteses do documento: margem {policy.margin_bps / 100:g}%, "
                  f"conversão {p0 / 100:g}%→{p1 / 100:g}%. Sugestão ilustrativa, não aplicada.")
        ctx.events.discount_proposed("discount_specialist", best["recommendation_id"], bps,
                                     discount, delta, reason)
        return _close(ctx, AgentResult("discount_specialist", "done", {"suggested": True, "discount_cents": discount},
                           f"Desconto sugerido ao gestor com base em \"{policy.title}\" (aguarda aprovação).", "low",
                           ["lucro estimado com hipóteses de demonstração, não com dados reais"]))
