"""Curador: a IA julga se cada item devolvido pelo iFood é o que o cliente pediu.

Ex.: para "pizza para 2", "Pastel de Pizza" não é pizza; "Pizza Brownie" é sobremesa; "Pizza R$ 8,99"
numa esfiharia provavelmente é esfiha. O julgamento só vale para itens que vieram da busca (a IA não
cria item nem preço). Sem IA disponível, o planejador usa o filtro por palavras como reserva.
"""
from __future__ import annotations

import json

from .ai import ask
from .models import AgentResult, SessionContext, WorkingState
from .registry import AgentContext, AgentDefinition

MAX_ITEMS = 25
SYSTEM = ("Você é o Curador de um chatbot de compras de comida. Julgue, item por item, se ele atende ao "
          "pedido do cliente como refeição: 'sim' (é o que foi pedido), 'parcial' (parecido, mas não exato) "
          "ou 'nao' (outro prato, sobremesa/bebida quando pediram refeição, porção pequena demais para o "
          "pedido, acompanhamento). Use só os itens informados; não invente itens nem preços. Motivo em até "
          "12 palavras, em português.")
SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["product_id", "fit", "reason"], "properties": {
        "product_id": {"type": "string"}, "fit": {"type": "string", "enum": ["sim", "parcial", "nao"]},
        "reason": {"type": "string"}}}}}}


class Curator:
    definition = AgentDefinition(
        "curator", "Curador", "Julgamento de relevância (IA)",
        "Usa IA para julgar se cada oferta encontrada é o que o cliente pediu", ["relevance_judgment"])
    order = 15

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return bool(state.offers) and not state.ai_fit

    def run(self, ctx: AgentContext) -> AgentResult:
        st, c = ctx.state, ctx.state.constraints
        items = [{"product_id": o.product_id, "item": o.name, "restaurante": o.merchant_name,
                  "preco_unitario": f"R$ {o.unit_price_cents / 100:.2f}"} for o in st.offers[:MAX_ITEMS]]
        prompt = (f"Pedido do cliente: {ctx.session.message_text}\n"
                  f"PRATO_JSON: {json.dumps(list(st.query_terms), ensure_ascii=False)}\n"
                  f"Pessoas: {c.party_size}; restrições: {list(c.dietary)}\n"
                  f"ITENS_JSON: {json.dumps(items, ensure_ascii=False)}")
        answer = ask(ctx, "curator", SYSTEM, prompt, SCHEMA)
        if answer is None:
            return AgentResult("curator", "done", {"judged": 0},
                               "IA não respondeu (ver motivo no painel): relevância pelo filtro de palavras (reserva).", "low",
                               ["julgamento por IA indisponível"])
        known = {o.product_id for o in st.offers}
        st.ai_fit = {i["product_id"]: (i["fit"], i["reason"].strip()[:120])
                     for i in answer["items"] if i["product_id"] in known}
        good = [pid for pid, (fit, _) in st.ai_fit.items() if fit == "sim"]
        bad = [(pid, why) for pid, (fit, why) in st.ai_fit.items() if fit == "nao"]
        names = {o.product_id: o.name for o in st.offers}
        dropped = "; ".join(f"{names[pid]}: {why}" for pid, why in bad[:3])
        return AgentResult("curator", "done", {"judged": len(st.ai_fit), "fit": len(good), "rejected": len(bad)},
                           f"IA julgou {len(st.ai_fit)} item(ns): {len(good)} atendem ao pedido"
                           + (f"; descartados, ex.: {dropped}" if dropped else "") + ".", "medium")
