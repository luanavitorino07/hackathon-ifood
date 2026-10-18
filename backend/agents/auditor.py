"""Auditor: verificação independente, por algoritmo, de cada proposta antes de chegar ao cliente."""
from __future__ import annotations

from typing import Any

from .models import (VEGETARIAN_ALL, VEGETARIAN_OPTION, AgentResult, SessionContext, WorkingState,
                     filtered_mark, slug, soft_unverified, tag_requirements)
from .registry import AgentContext, AgentDefinition


def audit_recommendation(rec: dict[str, Any], st: WorkingState) -> list[str]:
    issues: list[str] = []
    c = st.constraints
    by_id = {o.product_id: o for o in st.offers}
    items = rec["items"]
    if not items:
        issues.append("Proposta sem itens")
    for it in items:
        offer = by_id.get(it["product_id"])
        if offer is None:
            issues.append(f"Item {it['product_id']} não consta nas ofertas pesquisadas")
        elif offer.unit_price_cents != it["unit_price_cents"]:
            issues.append(f"Preço de {it['product_id']} diverge da oferta pesquisada")
        elif offer.merchant_id != rec["merchant_id"]:
            issues.append(f"Item {it['product_id']} pertence a outro restaurante")
        if it["quantity"] <= 0:
            issues.append(f"Quantidade inválida em {it['product_id']}")
    subtotal = sum(i["quantity"] * i["unit_price_cents"] for i in items)
    if rec["subtotal_cents"] != subtotal:
        issues.append("Subtotal não confere com os itens")
    parts = (rec["delivery_fee_cents"], rec["other_fees_cents"])
    expected = subtotal + parts[0] + parts[1] - rec["discount_cents"] if None not in parts else None
    if rec["total_cents"] != expected:
        issues.append("Total não confere (ou preenchido com taxas desconhecidas)")
    if rec["discount_cents"] != 0:
        issues.append("Desconto aplicado sem autorização")
    if rec["data_origin"] != st.data_origin:
        issues.append("Origem dos dados divergente da pesquisa")
    shown = rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"]
    if c.budget_cents is not None and shown > c.budget_cents:
        issues.append("Acima do orçamento informado")
    if st.price_ceiling_cents is not None and shown >= st.price_ceiling_cents:
        issues.append("Não é mais barata que a opção anterior")
    unverified = soft_unverified(c, st.offers)
    veg = [by_id[i["product_id"]].tags for i in items if i["product_id"] in by_id]
    proven = "vegetarian" not in unverified
    ok_veg = (lambda t: "vegetarian" in t) if proven else \
        (lambda t: "vegetarian" in t or filtered_mark("VEGETARIAN") in t)
    if VEGETARIAN_ALL in c.dietary and not all(ok_veg(t) for t in veg):
        issues.append("Contém item não vegetariano")
    if VEGETARIAN_OPTION in c.dietary and not any(ok_veg(t) for t in veg):
        issues.append("Sem opção vegetariana")
    for r in unverified:  # restrição branda sem tag: só passa se a proposta avisar o cliente
        if not any(f"'{r}' não comprovada" in w for w in rec["warnings"]):
            issues.append(f"Restrição '{r}' não comprovada sem aviso ao cliente")
    for req in tag_requirements(c, st.offers):  # restrição sem comprovação nos dados nunca é aprovada
        for it in items:
            offer = by_id.get(it["product_id"])
            if offer is None or req not in {slug(t) for t in offer.tags}:
                issues.append(f"Restrição '{req}' não verificada em {it['product_id']}")
                break
    if c.party_size and sum(i["quantity"] for i in items) < c.party_size:
        issues.append("Quantidade insuficiente para o número de pessoas")
    return issues


class Auditor:
    definition = AgentDefinition(
        "auditor", "Auditor", "Verificação de consistência",
        "Confere restrições, totais e origem dos dados de cada proposta", ["audit"])
    order = 30

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return bool(state.recommendations)

    def run(self, ctx: AgentContext) -> AgentResult:
        st = ctx.state
        st.issues = {r["recommendation_id"]: audit_recommendation(r, st) for r in st.recommendations}
        st.approved_ids = [rid for rid, problems in st.issues.items() if not problems]
        rejected = len(st.issues) - len(st.approved_ids)
        status = "done" if st.approved_ids else "needs_info"
        return AgentResult(
            "auditor", status, {"approved": len(st.approved_ids), "rejected": rejected},
            f"{len(st.approved_ids)} aprovada(s), {rejected} rejeitada(s) pelas verificações algorítmicas.",
            "high", [], [] if st.approved_ids else ["proposta válida"])
