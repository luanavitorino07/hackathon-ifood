"""Planejador: monta pedidos candidatos por algoritmo (sem LLM) respeitando as restrições."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .events import new_id
from .models import (VEGETARIAN_ALL, VEGETARIAN_OPTION, AgentResult, Constraints, Offer,
                     SessionContext, WorkingState, filtered_mark, slug, soft_unverified,
                     tag_requirements)
from .registry import AgentContext, AgentDefinition
from .relevance import relevant

MAX_RECOMMENDATIONS = 6  # candidatas; o orquestrador apresenta no máximo 3 após a personalização


def is_vegetarian(offer: Offer, proven: bool = True) -> bool:
    """Com prova (tag), exige a tag; sem prova, aceita item vindo da busca filtrada do iFood."""
    return "vegetarian" in offer.tags or (not proven and filtered_mark("VEGETARIAN") in offer.tags)


def has_tags(offer: Offer, required: tuple[str, ...]) -> bool:
    have = {slug(t) for t in offer.tags}
    return all(r in have for r in required)


def _pick(pool: list[Offer], units: int, c: Constraints, premium: bool, required: tuple[str, ...],
          veg_enforced: bool) -> list[tuple[Offer, int]] | None:
    """Escolhe `units` itens de um restaurante. None se as restrições não puderem ser atendidas."""
    eligible = [o for o in pool if has_tags(o, required)
                and not (VEGETARIAN_ALL in c.dietary and not is_vegetarian(o, veg_enforced))]
    if not eligible:
        return None
    ordered = sorted(eligible, key=lambda o: (o.unit_price_cents, o.product_id), reverse=premium)
    chosen: list[Offer] = []
    if VEGETARIAN_OPTION in c.dietary and VEGETARIAN_ALL not in c.dietary:
        veg = [o for o in ordered if is_vegetarian(o, veg_enforced)]
        if not veg:
            return None
        chosen.append(veg[0])
    # econômica: completa com o item mais barato; a outra opção varia os itens (rodízio).
    fill = 0
    while len(chosen) < max(units, 1):
        chosen.append(ordered[fill % len(ordered)] if premium else ordered[0])
        fill += 1
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


def _same_items(a: dict[str, Any], b: dict[str, Any]) -> bool:
    key = lambda r: sorted((i["product_id"], i["quantity"]) for i in r["items"])  # noqa: E731
    return a["merchant_id"] == b["merchant_id"] and key(a) == key(b)


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
        open_offers = [o for o in st.offers if o.is_open is not False]
        closed = len(st.offers) - len(open_offers)
        pool_offers, missing_terms = relevant(open_offers, st.query_terms)
        if st.query_terms and not pool_offers:
            st.relevance_miss = True
            st.recommendations = []
            limitations = [f"{closed} oferta(s) de restaurante fechado descartada(s)"] if closed else []
            return AgentResult("planner", "needs_info", {"recommendations": 0},
                               f"Nenhuma oferta corresponde a '{' '.join(st.query_terms)}'.", "low",
                               limitations, [f"oferta de {' '.join(st.query_terms)}"])
        by_merchant: dict[str, list[Offer]] = defaultdict(list)
        for o in pool_offers:
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
                if missing_terms:
                    warnings.append(f"Não encontrei exatamente '{' '.join(sorted(missing_terms))}': "
                                    "esta é a opção mais próxima do que você pediu")
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
                if any(_same_items(r, rec) for r in recs):
                    continue
                recs.append(rec)
        recs.sort(key=lambda r: (r["total_cents"] is None, r["total_cents"] or r["subtotal_cents"]))
        # variedade: a melhor opção de cada restaurante primeiro, depois as demais por preço
        firsts = [r for i, r in enumerate(recs) if all(o["merchant_id"] != r["merchant_id"] for o in recs[:i])]
        st.recommendations = (firsts + [r for r in recs if r not in firsts])[:MAX_RECOMMENDATIONS]
        st.recommendations.sort(key=lambda r: (r["total_cents"] is None, r["total_cents"] or r["subtotal_cents"]))
        limitations = []
        if closed:
            limitations.append(f"{closed} oferta(s) de restaurante fechado descartada(s)")
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
