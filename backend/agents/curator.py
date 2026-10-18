"""Curador: a IA julga se cada item devolvido pelo iFood é o que o cliente pediu.

Ex.: para "pizza para 2", "Pastel de Pizza" não é pizza; "Pizza Brownie" é sobremesa; "Pizza R$ 8,99"
numa esfiharia provavelmente é esfiha. O julgamento só vale para itens que vieram da busca (a IA não
cria item nem preço). Sem IA disponível, o planejador usa o filtro por palavras como reserva.
"""
from __future__ import annotations

import json

from .ai import ask
from .models import (LIFESTYLE_RESTRICTIONS, AgentResult, SessionContext, WorkingState, base_restriction,
                     restriction_label, slug)
from .registry import AgentContext, AgentDefinition

MAX_ITEMS = 30
SYSTEM = ("Você é o Curador de um chatbot de compras de comida. Julgue, item por item, se ele atende ao "
          "pedido do cliente: 'sim' (é o que foi pedido), 'parcial' (parecido, mas não exato) ou 'nao' (outro "
          "prato, bebida/acompanhamento quando pediram comida, porção pequena demais, ou contraria uma "
          "preferência explícita, ex.: 'monte o seu' quando pediram pronto). Itens com papel 'prato' são julgados "
          "só contra o PRATO: complementos pedidos (bebida etc.) já foram buscados à parte, então um hambúrguer "
          "sem bebida continua 'sim'; 'combo' é preferência, não exigência. Item com papel 'complemento: X' é "
          "julgado só contra X (ex.: Coca-Cola Zero lata é 'sim' para 'coca zero'). Em 'inclui', liste os "
          "COMPLEMENTOS_JSON que um item 'prato' já traz (ex.: 'Combo X-Burger + Coca lata' inclui 'coca'; "
          "'Combo + Bebida' ou '+ Refrigerante' a escolher também inclui um refrigerante pedido, como 'coca zero'). Em 'serves', diga para quantas "
          "pessoas o item serve (lanche ou marmita = 1; pizza grande ou 'combo 2 pizzas' = 2; combo família = 4); "
          "null se não der para saber. Restrições alimentares NÃO entram no 'fit' (nunca descarte por restrição): "
          "use os ids de RESTRICOES_JSON. Em 'atende_restricoes', as de dieta (vegetariano/vegano) que o nome deixa "
          "claro que o item atende (ex.: poke de tofu, hambúrguer de falafel); na dúvida, não liste. Em "
          "'viola_restricoes', as que o item contraria ou provavelmente contraria (ex.: falafel para intolerância "
          "a grão de bico; milk-shake para sem lactose; bacon para vegano); sempre inclua 'viola_restricoes' em "
          "todo item quando houver restrições (lista vazia se nenhuma). Se nenhum item for 'sim' "
          "ou nenhum 'sim' atender a alguma restrição, sugira em 'nova_busca' um termo curto de busca no iFood com "
          "mais chance de atender (ex.: 'sorbet', 'poke vegano'); senão null. Use só os itens informados; não invente "
          "itens nem preços. Motivo em até 12 palavras, em português.")
SCHEMA = {"type": "object", "required": ["items"], "properties": {
    "items": {"type": "array", "items": {
        "type": "object", "required": ["product_id", "fit", "reason"], "properties": {
            "product_id": {"type": "string"}, "fit": {"type": "string", "enum": ["sim", "parcial", "nao"]},
            "reason": {"type": "string"}, "serves": {"type": ["integer", "null"]},
            "atende_restricoes": {"type": "array", "items": {"type": "string"}},
            "viola_restricoes": {"type": "array", "items": {"type": "string"}},
            "inclui": {"type": "array", "items": {"type": "string"}}}}},
    "nova_busca": {"type": ["string", "null"]}}}


def _hint(value: object, current: tuple[str, ...]) -> str | None:
    """Termo de nova busca plausível (curto, só letras) e diferente da busca atual."""
    if not isinstance(value, str):
        return None
    hint = " ".join(value.split()).strip(" .'\"")[:40]
    words = hint.lower().split()
    if not (1 <= len(words) <= 4) or not all(w.isalpha() for w in words) or words == [t.lower() for t in current]:
        return None
    return hint.lower()


def _ids(values: object, restrictions: dict[str, str]) -> set[str]:
    """Ids de restrição citados pela IA, aceitando o id, o rótulo ou variações de grafia."""
    out: set[str] = set()
    for v in values if isinstance(values, list) else []:
        x = slug(str(v))
        for rid, label in restrictions.items():
            if x and (x == rid or x == slug(label) or rid in x or x in rid):
                out.add(rid)
    return out


def _satisfied(item: dict, restrictions: dict[str, str], evaluated: bool = False) -> tuple[str, ...]:
    """Dieta (vegetariano/vegano) só com confirmação explícita; saúde ('sem X', intolerância, alergia) quando a
    IA julgou o item e não apontou violação. `evaluated`: a IA usou 'viola_restricoes' na resposta (omitir a
    lista vazia num item não significa que deixou de avaliá-lo)."""
    yes, no = _ids(item.get("atende_restricoes"), restrictions), _ids(item.get("viola_restricoes"), restrictions)
    checked = evaluated or isinstance(item.get("viola_restricoes"), list)
    return tuple(r for r in restrictions
                 if r not in no and (r in yes or (checked and r not in LIFESTYLE_RESTRICTIONS)))


def _sample(st: WorkingState) -> list:
    """Até MAX_ITEMS itens, reservando espaço para os complementos (que vêm depois na lista)."""
    extras = [o for o in st.offers if o.product_id in st.extra_of][:6]
    main = [o for o in st.offers if o.product_id not in st.extra_of][:MAX_ITEMS - len(extras)]
    return main + extras


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
                  "preco_unitario": f"R$ {o.unit_price_cents / 100:.2f}",
                  "papel": f"complemento: {st.extra_of[o.product_id]}" if o.product_id in st.extra_of else "prato"}
                 for o in _sample(st)]
        restrictions = {base_restriction(r): restriction_label(r) for r in c.dietary}
        prompt = (f"Pedido do cliente: {ctx.session.message_text}\n"
                  + (f"Pedido entendido (com o contexto da conversa): {st.request_summary}\n" if st.request_summary else "")
                  + f"PRATO_JSON: {json.dumps(list(st.query_terms), ensure_ascii=False)}\n"
                  f"COMPLEMENTOS_JSON: {json.dumps(list(st.extra_terms), ensure_ascii=False)}\n"
                  f"Pessoas: {c.party_size}; preferências: {list(c.preferences)}\n"
                  f"RESTRICOES_JSON: {json.dumps([{'id': k, 'descricao': v} for k, v in restrictions.items()], ensure_ascii=False)}\n"
                  f"ITENS_JSON: {json.dumps(items, ensure_ascii=False)}")
        answer = ask(ctx, "curator", SYSTEM, prompt, SCHEMA)
        if answer is None:
            return AgentResult("curator", "done", {"judged": 0},
                               "IA não respondeu (ver motivo no painel): relevância pelo filtro de palavras (reserva).", "low",
                               ["julgamento por IA indisponível"])
        known = {o.product_id for o in st.offers}
        st.ai_fit = {i["product_id"]: (i["fit"], i["reason"].strip()[:120])
                     for i in answer["items"] if i["product_id"] in known}
        st.ai_serves = {i["product_id"]: i["serves"] for i in answer["items"]
                        if i["product_id"] in known and isinstance(i.get("serves"), int) and 1 <= i["serves"] <= 12}
        st.ai_includes = {i["product_id"]: tuple(x for x in st.extra_terms if slug(x) in
                                                 {slug(str(v)) for v in i.get("inclui") or []})
                          for i in answer["items"] if i["product_id"] in known and i.get("inclui")}
        evaluated = any(isinstance(i.get("viola_restricoes"), list) for i in answer["items"])
        st.ai_restrictions = {i["product_id"]: _satisfied(i, restrictions, evaluated)
                              for i in answer["items"] if i["product_id"] in known}
        good = [pid for pid, (fit, _) in st.ai_fit.items() if fit == "sim" and pid not in st.extra_of]
        covered = all(any(r in st.ai_restrictions.get(pid, ()) for pid in good) for r in restrictions)
        st.research_hint = None if good and covered else _hint(answer.get("nova_busca"), st.query_terms)
        bad = [(pid, why) for pid, (fit, why) in st.ai_fit.items() if fit == "nao" and pid not in st.extra_of]
        names = {o.product_id: o.name for o in st.offers}
        dropped = "; ".join(f"{names[pid]}: {why}" for pid, why in bad[:3])
        return AgentResult("curator", "done", {"judged": len(st.ai_fit), "fit": len(good), "rejected": len(bad)},
                           f"IA julgou {len(st.ai_fit)} item(ns): {len(good)} atendem ao pedido"
                           + (f"; descartados, ex.: {dropped}" if dropped else "")
                           + (f"; com restrições atendidas: {sum(1 for v in st.ai_restrictions.values() if v)}"
                              if restrictions else "") + ".", "medium")
