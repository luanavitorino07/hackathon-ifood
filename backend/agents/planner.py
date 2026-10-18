"""Planejador: monta pedidos candidatos por algoritmo (sem LLM) respeitando as restrições."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .events import new_id
from .models import (VEGETARIAN_ALL, VEGETARIAN_OPTION, AgentResult, Constraints, Offer,
                     SessionContext, WorkingState, filtered_mark, option_requirements, restriction_label,
                     slug, soft_unverified, tag_requirements)
from .registry import AgentContext, AgentDefinition
from .relevance import relevant

MAX_RECOMMENDATIONS = 6  # candidatas; o orquestrador apresenta no máximo 3 após a personalização


def is_vegetarian(offer: Offer, proven: bool = True) -> bool:
    """Com prova (tag), exige a tag; sem prova, aceita item vindo da busca filtrada do iFood."""
    return "vegetarian" in offer.tags or (not proven and filtered_mark("VEGETARIAN") in offer.tags)


def has_tags(offer: Offer, required: tuple[str, ...], ai: dict[str, tuple[str, ...]] | None = None) -> bool:
    """Cada restrição exigida vem comprovada pela tag do iFood ou foi avaliada pela IA do Curador."""
    have = {slug(t) for t in offer.tags} | set((ai or {}).get(offer.product_id, ()))
    return all(r in have for r in required)


def ai_only(offer: Offer, restriction: str, ai: dict[str, tuple[str, ...]]) -> bool:
    """A restrição só foi atendida pela avaliação da IA (sem tag do iFood)."""
    return restriction not in {slug(t) for t in offer.tags} and restriction in ai.get(offer.product_id, ())


def _pick(pool: list[Offer], units: int, c: Constraints, premium: bool, required: tuple[str, ...],
          veg_enforced: bool, serves: dict[str, int] | None = None,
          ai: dict[str, tuple[str, ...]] | None = None) -> list[tuple[Offer, int]] | None:
    """Escolhe itens de um restaurante até servir `units` pessoas (a IA informa quantas pessoas cada
    item serve; sem isso, 1 por pessoa). None se as restrições não puderem ser atendidas."""
    serves, ai = serves or {}, ai or {}
    portions = lambda o: serves.get(o.product_id, 1)  # noqa: E731
    veg = lambda o: is_vegetarian(o, veg_enforced) or "vegetarian" in ai.get(o.product_id, ())  # noqa: E731
    eligible = [o for o in pool if has_tags(o, required, ai)
                and not (VEGETARIAN_ALL in c.dietary and not veg(o))]
    if not eligible:
        return None
    # econômica: menor preço por pessoa atendida
    ordered = sorted(eligible, key=lambda o: (o.unit_price_cents / portions(o), o.product_id), reverse=premium)
    chosen: list[Offer] = []
    if VEGETARIAN_OPTION in c.dietary and VEGETARIAN_ALL not in c.dietary:
        options = [o for o in ordered if veg(o)]
        if not options:
            return None
        chosen.append(options[0])
    for r in option_requirements(c):  # "um amigo é vegano": ao menos um item atende
        if any(has_tags(o, (r,), ai) for o in chosen):
            continue
        options = [o for o in ordered if has_tags(o, (r,), ai)]
        if not options:
            return None
        chosen.append(options[0])
    # econômica: completa com o item mais barato; a outra opção varia os itens (rodízio).
    fill = 0
    while sum(portions(o) for o in chosen) < max(units, 1):
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


def _ai_select(st: WorkingState, offers: list[Offer]) -> tuple[list[Offer], set[str]] | None:
    """Seleção pelo julgamento da IA do Curador; None se não houver julgamento."""
    if not st.ai_fit:
        return None
    fit = {o.product_id: st.ai_fit.get(o.product_id, ("parcial", ""))[0] for o in offers}
    yes = [o for o in offers if fit[o.product_id] == "sim"]
    if yes:
        return yes, set()
    partial = [o for o in offers if fit[o.product_id] == "parcial"]
    return partial, (set(st.query_terms) or {"o prato pedido"}) if partial else set(st.query_terms)


class Planner:
    definition = AgentDefinition(
        "planner", "Planejador de compra", "Combinação de pedidos",
        "Combina itens respeitando orçamento, quantidade e restrições", ["order_planning"])
    order = 20

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return bool(state.offers)

    @staticmethod
    def _select(st: WorkingState, offers: list[Offer]) -> tuple[list[Offer], set[str]]:
        by_ai = _ai_select(st, offers)
        if by_ai is not None:
            if not by_ai[0]:
                st.relevance_miss = True
            return by_ai
        return relevant(offers, st.query_terms)  # reserva: filtro por palavras

    def run(self, ctx: AgentContext) -> AgentResult:
        st, c = ctx.state, ctx.state.constraints
        required = tag_requirements(c, st.offers)
        unverified = soft_unverified(c, st.offers)
        veg_enforced = "vegetarian" not in unverified
        units = c.party_size or 1
        open_offers = [o for o in st.offers if o.is_open is not False]
        closed = len(st.offers) - len(open_offers)
        pool_offers, missing_terms = self._select(st, open_offers)
        if not pool_offers and (st.query_terms or st.relevance_miss):
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
                picked = _pick(pool, units, c, premium, required, veg_enforced, st.ai_serves,
                               st.ai_restrictions)
                if picked is None:
                    skipped_restriction += 1
                    continue
                labels = ", ".join(restriction_label(r) for r in c.dietary)
                reasons = [f"Considera as restrições: {labels}" if c.dietary else "Sem restrições alimentares informadas"]
                warnings: list[str] = [
                    f"Restrição '{r}' não comprovada pelo iFood (filtro de busca solicitado): "
                    "confira a descrição do item" for r in unverified]
                for r in sorted({r for o, _ in picked for r in required + option_requirements(c)
                                 + (("vegetarian",) if VEGETARIAN_ALL in c.dietary or VEGETARIAN_OPTION in c.dietary
                                    else ()) if ai_only(o, r, st.ai_restrictions)}):
                    warnings.append(f"Restrição '{restriction_label(r)}' avaliada pela IA pelo nome do item "
                                    "(o iFood não informa): confirme com o restaurante antes de pedir")
                if missing_terms:
                    wanted = st.request_summary or " ".join(sorted(missing_terms))
                    warnings.append(f"Não encontrei exatamente o que você pediu ({wanted}): "
                                    "esta é a opção mais próxima")
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
                    if st.cheapest_over_budget_cents is None or known < st.cheapest_over_budget_cents:
                        st.cheapest_over_budget_cents = known
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
        ctx.events.agent_message("planner", "auditor", ctx.task_id, "request",
                                 f"Confere {len(st.recommendations)} proposta(s): preços, totais, quantidade e restrições?")
        return AgentResult("planner", "done", {"recommendations": len(st.recommendations)},
                           f"{len(st.recommendations)} proposta(s) montada(s) por regra determinística.",
                           "medium", limitations)
