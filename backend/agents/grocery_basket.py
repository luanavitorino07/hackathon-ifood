"""Montador da cesta: escolhe, em cada mercado, o produto e a quantidade de cada item da lista.

A IA julga se cada produto encontrado é o item pedido ("leite" ≠ "doce de leite"), quantas unidades
cobrem o tamanho pedido ("arroz 5 kg" com pacote de 1 kg = 5) e quais restrições o produto contraria.
O código monta a cesta: só produtos que vieram da busca, preço da busca, um mercado por proposta
(uma entrega), total calculado aqui e orçamento respeitado. Sem IA, vale a correspondência por palavras.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .ai import ask
from .curator import _satisfied
from .grocery import ListItem, list_text
from .models import (LIFESTYLE_RESTRICTIONS, AgentResult, Offer, SessionContext, WorkingState, base_restriction,
                     restriction_label, slug)
from .planner import MAX_RECOMMENDATIONS, build_recommendation
from .registry import AgentContext, AgentDefinition
from .relevance import _words

BASKET_ID = "grocery_basket"
MAX_PER_ITEM = 8  # produtos por item da lista enviados à IA
SYSTEM = ("Você é o Montador da cesta de um app de compras de supermercado. Para cada produto de PRODUTOS_JSON, "
          "diga se ele é o item da lista indicado em 'item_id' (LISTA_JSON): 'sim' (é o item), 'parcial' (parecido, "
          "outra marca/versão aceitável) ou 'nao' (outro produto: ex. 'doce de leite' para 'leite', 'tempero' para "
          "'frango'). Em 'quantidade', diga quantas unidades desse produto comprar para atender ao pedido: use "
          "'quantidade' e 'detalhe' do item (ex.: detalhe '5 kg' e pacote de 1 kg = 5; pacote de 5 kg = 1; "
          "'2x leite' = 2); null se não der para saber. Em 'viola_restricoes', os ids de RESTRICOES_JSON que o "
          "produto contraria ou provavelmente contraria (ex.: leite integral para sem lactose); lista vazia se "
          "nenhum. Em 'atende_restricoes', as de dieta (vegetariano/vegano) que o nome deixa claro que atende. Use "
          "só os produtos informados; não invente produtos nem preços. Motivo em até 10 palavras.")
SCHEMA = {"type": "object", "required": ["produtos"], "properties": {
    "produtos": {"type": "array", "items": {
        "type": "object", "required": ["product_id", "fit"], "properties": {
            "product_id": {"type": "string"}, "fit": {"type": "string", "enum": ["sim", "parcial", "nao"]},
            "quantidade": {"type": ["integer", "null"]}, "motivo": {"type": "string"},
            "atende_restricoes": {"type": "array", "items": {"type": "string"}},
            "viola_restricoes": {"type": "array", "items": {"type": "string"}}}}}}}


def _rule_fit(offer: Offer, item: ListItem) -> str:
    """Reserva sem IA: todas as palavras do item no nome = 'sim'; alguma = 'parcial'."""
    words = _words(offer.name)
    terms = [w for w in _words(item.name) if len(w) >= 3] or _words(item.name)
    hits = sum(1 for t in terms if any(w.startswith(t[:5]) for w in words))
    return "sim" if hits == len(terms) else "parcial" if hits else "nao"


def required_restrictions(st: WorkingState) -> tuple[str, ...]:
    """Restrições que valem para todos os itens da cesta ("para ao menos uma pessoa" não se aplica a mercado)."""
    return tuple(dict.fromkeys(base_restriction(r) for r in st.constraints.dietary
                               if not r.endswith("_option")))


def restriction_ok(st: WorkingState, offer: Offer, ai_ran: bool) -> tuple[bool, bool]:
    """(pode entrar na cesta, só a IA avaliou). Sem IA, entra com aviso de 'não verificada'."""
    required = required_restrictions(st)
    if not required:
        return True, False
    tags = {slug(t) for t in offer.tags}
    ai = set(st.ai_restrictions.get(offer.product_id, ()))
    if all(r in tags for r in required):
        return True, False
    if not ai_ran:
        return True, False
    return all(r in tags or r in ai for r in required), True


class GroceryBasket:
    definition = AgentDefinition(
        BASKET_ID, "Montador da cesta", "Cesta de supermercado (IA)",
        "Usa IA para escolher, em cada mercado, o produto e a quantidade de cada item da lista de compras",
        ["grocery_basket"])
    order = 20

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return bool(state.shopping_list) and bool(state.offers)

    def _judge(self, ctx: AgentContext, open_offers: list[Offer]) -> bool:
        st = ctx.state
        ids = {i.name: f"i{n}" for n, i in enumerate(st.shopping_list, 1)}
        per_item: dict[str, int] = defaultdict(int)
        products = []
        for o in open_offers:
            item = st.grocery_of.get(o.product_id)
            if item in ids and per_item[item] < MAX_PER_ITEM * 3:
                per_item[item] += 1
                products.append({"product_id": o.product_id, "item_id": ids[item], "produto": o.name,
                                 "mercado": o.merchant_name, "preco": f"R$ {o.unit_price_cents / 100:.2f}"})
        restrictions = {r: restriction_label(r) for r in required_restrictions(st)}
        prompt = (f"Pedido do cliente: {ctx.session.message_text}\n"
                  f"LISTA_JSON: {json.dumps([{'id': ids[i.name], 'item': i.name, 'quantidade': i.quantity, 'detalhe': i.note} for i in st.shopping_list], ensure_ascii=False)}\n"
                  f"RESTRICOES_JSON: {json.dumps([{'id': k, 'descricao': v} for k, v in restrictions.items()], ensure_ascii=False)}\n"
                  f"PRODUTOS_JSON: {json.dumps(products, ensure_ascii=False)}")
        answer = ask(ctx, BASKET_ID, SYSTEM, prompt, SCHEMA)
        if answer is None:
            return False
        known = {p["product_id"] for p in products}
        judged = [p for p in answer["produtos"] if p["product_id"] in known]
        st.ai_fit = {p["product_id"]: (p["fit"], str(p.get("motivo") or "").strip()[:120]) for p in judged}
        st.ai_quantity = {p["product_id"]: p["quantidade"] for p in judged
                          if isinstance(p.get("quantidade"), int) and 1 <= p["quantidade"] <= 50}
        evaluated = any(isinstance(p.get("viola_restricoes"), list) for p in judged)
        st.ai_restrictions = {p["product_id"]: _satisfied(p, restrictions, evaluated) for p in judged}
        return bool(st.ai_fit)

    def run(self, ctx: AgentContext) -> AgentResult:
        st, c = ctx.state, ctx.state.constraints
        open_offers = [o for o in st.offers if o.is_open is not False and o.product_id in st.grocery_of]
        closed = sum(1 for o in st.offers if o.is_open is False)
        ai_ran = self._judge(ctx, open_offers)
        by_name = {i.name: i for i in st.shopping_list}
        fit = (lambda o: st.ai_fit.get(o.product_id, ("nao", ""))[0]) if ai_ran else \
            (lambda o: _rule_fit(o, by_name[st.grocery_of[o.product_id]]))
        by_merchant: dict[str, list[Offer]] = defaultdict(list)
        for o in open_offers:
            by_merchant[o.merchant_id].append(o)
        required = required_restrictions(st)
        recs: list[dict[str, Any]] = []
        skipped_budget = 0
        for pool in by_merchant.values():
            picked: list[tuple[Offer, int]] = []
            missing: list[str] = []
            by_ai: set[str] = set()
            for item in st.shopping_list:
                options = []
                for o in pool:
                    if st.grocery_of.get(o.product_id) != item.name or fit(o) == "nao":
                        continue
                    allowed, only_ai = restriction_ok(st, o, ai_ran)
                    if allowed:
                        options.append((o, only_ai))
                if not options:
                    missing.append(item.name)
                    continue
                qty = lambda o: st.ai_quantity.get(o.product_id, item.quantity)  # noqa: E731
                best, only_ai = min(options, key=lambda x: (fit(x[0]) != "sim", x[0].unit_price_cents * qty(x[0]),
                                                            x[0].product_id))
                picked.append((best, qty(best)))
                if only_ai:
                    by_ai.update(r for r in required if r not in {slug(t) for t in best.tags})
            if not picked:
                continue
            covered = len(picked)
            reasons = [f"{covered} de {len(st.shopping_list)} itens da lista neste mercado"]
            warnings: list[str] = []
            if missing:
                warnings.append("Não encontrei neste mercado: " + ", ".join(missing))
            if required and not ai_ran:
                warnings.append("Restrições não verificadas: " + ", ".join(restriction_label(r) for r in required)
                                + "; confira os rótulos")
            for r in sorted(by_ai - LIFESTYLE_RESTRICTIONS):
                warnings.append(f"Restrição '{restriction_label(r)}' avaliada pela IA: confira o rótulo")
            if any(i.note for i in st.shopping_list) and not ai_ran:
                warnings.append("Tamanhos pedidos não conferidos: confira as embalagens")
            rec = build_recommendation(pool[0], picked, st.data_origin, reasons, warnings)
            known = rec["total_cents"] if rec["total_cents"] is not None else rec["subtotal_cents"]
            if rec["total_cents"] is None:
                warnings.append("Total indisponível: taxa de entrega ou outras taxas desconhecidas")
            if c.budget_cents is not None and known > c.budget_cents:
                skipped_budget += 1
                if st.cheapest_over_budget_cents is None or known < st.cheapest_over_budget_cents:
                    st.cheapest_over_budget_cents = known
                continue
            if c.budget_cents is not None:
                reasons.append("Dentro do orçamento")
            if pool[0].merchant_id == st.preferred_merchant_id:
                reasons.append("Mesmo mercado da sua compra agendada")
            rec["_covered"] = covered
            recs.append(rec)
        best_cover = max((r["_covered"] for r in recs), default=0)
        recs = [r for r in recs if r["_covered"] * 2 >= best_cover]  # descarta mercados que cobrem bem menos
        recs.sort(key=lambda r: (-r.pop("_covered"), r["merchant_id"] != st.preferred_merchant_id,
                                 r["total_cents"] is None, r["total_cents"] or r["subtotal_cents"]))
        st.recommendations = recs[:MAX_RECOMMENDATIONS]
        limitations = []
        if closed:
            limitations.append(f"{closed} produto(s) de mercado fechado descartado(s)")
        if skipped_budget:
            limitations.append(f"{skipped_budget} cesta(s) acima do orçamento descartada(s)")
        if not ai_ran:
            limitations.append("julgamento por IA indisponível: correspondência por palavras (reserva)")
        if not st.recommendations:
            return AgentResult(BASKET_ID, "needs_info", {"recommendations": 0},
                               "Nenhum mercado com a lista dentro do orçamento e das restrições.", "low",
                               limitations, ["mercado com os itens da lista"])
        top = st.recommendations[0]
        ctx.events.agent_message(BASKET_ID, "auditor", ctx.task_id, "request",
                                 f"Confere {len(st.recommendations)} cesta(s)? Melhor: {top['merchant_name']} com "
                                 f"{len(top['items'])} de {len(st.shopping_list)} itens ({list_text(st.shopping_list)})")
        return AgentResult(BASKET_ID, "done", {"recommendations": len(st.recommendations), "ai": ai_ran},
                           f"{len(st.recommendations)} cesta(s) montada(s)"
                           + (" com julgamento da IA" if ai_ran else " por palavras (IA indisponível)") + ".",
                           "medium", limitations)
