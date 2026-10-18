"""Planejador: monta pedidos candidatos por algoritmo (sem LLM) respeitando as restrições."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .events import new_id
from .models import (VEGETARIAN_ALL, VEGETARIAN_OPTION, AgentResult, Constraints, Offer,
                     SessionContext, WorkingState, slug, soft_unverified, tag_requirements)
from .registry import AgentContext, AgentDefinition

MAX_RECOMMENDATIONS = 3


def is_vegetarian(offer: Offer) -> bool:
    return "vegetarian" in offer.tags


def has_tags(offer: Offer, required: tuple[str, ...]) -> bool:
    have = {slug(t) for t in offer.tags}
    return all(r in have for r in required)


def _pick(pool: list[Offer], units: int, c: Constraints, premium: bool, required: tuple[str, ...],
          veg_enforced: bool) -> list[tuple[Offer, int]] | None:
    """Escolhe `units` itens de um restaurante. None se as restrições não puderem ser atendidas."""
    eligible = [o for o in pool if has_tags(o, required)
                and not (veg_enforced and VEGETARIAN_ALL in c.dietary and not is_vegetarian(o))]
    if not eligible:
        return None
    ordered = sorted(eligible, key=lambda o: (o.unit_price_cents, o.product_id), reverse=premium)
    chosen: list[Offer] = []
    if veg_enforced and VEGETARIAN_OPTION in c.dietary and VEGETARIAN_ALL not in c.dietary:
        veg = [o for o in ordered if is_vegetarian(o)]
        if not veg:
            return None
        chosen.append(veg[0])
    while len(chosen) < max(units, 1):
        chosen.append(ordered[len(chosen) % len(ordered)])
    counts: dict[str, int] = defaultdict(int)
    by_id = {o.product_id: o for o in chosen}
    for o in chosen:
        counts[o.product_id] += 1
    return [(by_id[pid], q) for pid, q in counts.items()]


def build_recommendation(merchant: Offer, picked: list[tuple[Offer, int]], origin: str,
                         reasons: list[str], warnings: list[str]) -> dict[str, Any]:
    items = [{"product_id": o.product_id, "name": o.name, "quantity": q,
              "unit_price_cents": o.unit_price_cents} for o, q in picked]
    subtotal = sum(i["quantity"] * i["unit_price_cents"] for i in items)
    delivery, other = merchant.delivery_fee_cents, merchant.other_fees_cents
    if other is None:  # decisão do produto: a busca do iFood não informa taxa de serviço
        other = 0
        warnings.append("Taxa de serviço não informada pelo iFood: não incluída no total")
    total = subtotal + delivery + other if delivery is not None and other is not None else None
    return {
        "recommendation_id": new_id("rec"), "merchant_id": merchant.merchant_id,
        "merchant_name": merchant.merchant_name, "items": items, "currency": "BRL",
        "subtotal_cents": subtotal, "delivery_fee_cents": delivery, "other_fees_cents": other,
        "discount_cents": 0, "total_cents": total, "eta_minutes": merchant.eta_minutes,
        "reasons": reasons, "warnings": warnings, "data_origin": origin,
    }


class Planner:
    definition = AgentDefinition(
        "planner", "Planejador de compra", "Combinação de pedidos",
        "Combina itens respeitando orçamento, quantidade e restrições", ["order_planning"])
    order = 20

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return bool(state.offers)

    def run(self, ctx: AgentContext) -> AgentResult:
        st, c = ctx.state, ctx.state.constraints
        required = tag_requirements(c, st.offers)
        unverified = soft_unverified(c, st.offers)
        veg_enforced = "vegetarian" not in unverified
        units = c.party_size or 1
        by_merchant: dict[str, list[Offer]] = defaultdict(list)
        for o in st.offers:
            by_merchant[o.merchant_id].append(o)
        recs: list[dict[str, Any]] = []
        skipped_budget = skipped_restriction = 0
        for pool in by_merchant.values():
            for premium in (False, True):
                picked = _pick(pool, units, c, premium, required, veg_enforced)
                if picked is None:
                    skipped_restriction += 1
                    continue
                reasons = ["Atende as restrições verificáveis informadas" if c.dietary else "Sem restrições informadas"]
                warnings: list[str] = [
                    f"Restrição '{r}' não comprovada pelo iFood (filtro de busca solicitado): "
                    "confira a descrição do item" for r in unverified]
                rec = build_recommendation(pool[0], picked, st.data_origin, reasons, warnings)
                known = rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"]
                if st.price_ceiling_cents is not None:
                    if known >= st.price_ceiling_cents:
                        continue
                    reasons.append("Mais barata que a opção anterior")
                if rec["total_cents"] is None:
                    warnings.append("Total indisponível: taxa de entrega ou outras taxas desconhecidas")
                if c.budget_cents is None:
                    warnings.append("Orçamento não informado")
                elif known > c.budget_cents:
                    skipped_budget += 1
                    continue
                else:
                    reasons.append("Dentro do orçamento")
                if any(r["items"] == rec["items"] and r["merchant_id"] == rec["merchant_id"] for r in recs):
                    continue
                recs.append(rec)
        recs.sort(key=lambda r: (r["total_cents"] is None, r["total_cents"] or r["subtotal_cents"]))
        st.recommendations = recs[:MAX_RECOMMENDATIONS]
        limitations = []
        if skipped_budget:
            limitations.append(f"{skipped_budget} combinação(ões) acima do orçamento descartada(s)")
        if skipped_restriction:
            limitations.append(f"{skipped_restriction} restaurante(s) sem opção verificável para as restrições")
        if not st.recommendations:
            return AgentResult("planner", "needs_info", {"recommendations": 0},
                               "Nenhuma combinação atende e comprova orçamento e restrições.", "low",
                               limitations, ["orçamento ou restrições compatíveis com as ofertas"]
                               + [f"verificação da restrição '{r}'" for r in tag_requirements(c)])
        return AgentResult("planner", "done", {"recommendations": len(st.recommendations)},
                           f"{len(st.recommendations)} proposta(s) montada(s) por regra determinística.",
                           "medium", limitations)
