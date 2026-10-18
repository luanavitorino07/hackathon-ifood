"""Pesquisador: pede ofertas ao runtime (MCP via OpenCode) e valida o que volta."""
from __future__ import annotations

from typing import Any

from dataclasses import replace

from .models import (SOFT_FILTERS, VEGETARIAN_ALL, VEGETARIAN_OPTION, AgentResult, Offer, SessionContext,
                     WorkingState, dietary_filters, filtered_mark, option_requirements, restriction_label)
from .ports import RuntimeCall, RuntimeOutcome
from .registry import AgentContext, AgentDefinition
from .relevance import score

OFFER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["offers"],
    "properties": {
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["product_id", "name", "unit_price_cents", "merchant_id", "merchant_name"],
                "properties": {
                    "product_id": {"type": "string"},
                    "name": {"type": "string"},
                    "unit_price_cents": {"type": "integer", "minimum": 0},
                    "merchant_id": {"type": "string"},
                    "merchant_name": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "delivery_fee_cents": {"type": ["integer", "null"]},
                    "other_fees_cents": {"type": ["integer", "null"]},
                    "eta_minutes": {"type": ["integer", "null"]},
                    "is_open": {"type": ["boolean", "null"]},
                },
            },
        }
    },
}

GROCERIES = "GROCERIES"  # `merchantType` do searchOffers para supermercados
MAX_STORE_SEARCHES = 4  # buscas extras dentro do mercado escolhido, para completar a lista
EXTRA_RESTAURANTS = 3  # restaurantes do prato onde os complementos que faltam são procurados
MAX_EXTRA_STORE_SEARCHES = 4

SYSTEM = (
    "Você é o Pesquisador de um chatbot de compras. Use SOMENTE as ferramentas de busca "
    "autorizadas para listar ofertas reais. Não invente produtos nem preços; preços em centavos "
    "inteiros de BRL; use null para valores desconhecidos."
)


def _tool_context(session: SessionContext, state: WorkingState) -> dict[str, Any]:
    """Contexto estruturado mínimo: `location` (se houver) e `dietary_filters` (filtros de busca)."""
    context: dict[str, Any] = {}
    location = (session.initial_context or {}).get("location")
    if location:
        context["location"] = location
    filters = dietary_filters(state.constraints)
    if filters:
        context["dietary_filters"] = filters
    return context


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_offers(structured: dict[str, Any] | None) -> tuple[list[Offer], int]:
    """Valida ofertas; devolve (válidas, quantidade descartada)."""
    raw = (structured or {}).get("offers")
    if not isinstance(raw, list):
        return [], 0
    offers, dropped = [], 0
    for item in raw:
        try:
            price = item["unit_price_cents"]
            if not isinstance(price, int) or isinstance(price, bool) or price < 0:
                raise ValueError("preço inválido")
            ids = [item["product_id"], item["name"], item["merchant_id"], item["merchant_name"]]
            if not all(isinstance(v, str) and v for v in ids):
                raise ValueError("campo textual inválido")
            offers.append(Offer(
                product_id=item["product_id"], name=item["name"], unit_price_cents=price,
                merchant_id=item["merchant_id"], merchant_name=item["merchant_name"],
                tags=tuple(str(t) for t in item.get("tags") or ()),
                delivery_fee_cents=_int_or_none(item.get("delivery_fee_cents")),
                other_fees_cents=_int_or_none(item.get("other_fees_cents")),
                eta_minutes=_int_or_none(item.get("eta_minutes")),
                is_open=item.get("is_open") if isinstance(item.get("is_open"), bool) else None))
        except (KeyError, TypeError, ValueError, AttributeError):
            dropped += 1
    return offers, dropped


def origin_of(outcome: RuntimeOutcome) -> str:
    """`ifood_mcp` só se houve chamada MCP bem-sucedida comprovada; caso contrário `demo`."""
    real = any(t.provider == "ifood_mcp" and t.status == "succeeded" for t in outcome.tool_calls)
    return "ifood_mcp" if real else "demo"


class Researcher:
    definition = AgentDefinition(
        "researcher", "Pesquisador", "Busca de ofertas",
        "Pesquisa produtos e restaurantes pelas ferramentas MCP do iFood", ["offer_search"])
    order = 10

    def should_activate(self, session: SessionContext, state: WorkingState) -> bool:
        return not state.offers

    def _search(self, ctx: AgentContext, prompt: str, filters: list[str],
                scope: dict[str, str] | None = None) -> tuple[RuntimeOutcome, list[Offer], int]:
        context = _tool_context(ctx.session, ctx.state)
        context.pop("dietary_filters", None)
        if filters:
            context["dietary_filters"] = filters
        context.update(scope or {})  # `merchant_type` (vertical do iFood) e `merchant_id` (busca numa loja)
        outcome = ctx.runtime.run(RuntimeCall(
            agent_id="researcher", task_id=ctx.task_id, session_id=ctx.session.session_id,
            system=SYSTEM, prompt=prompt, output_schema=OFFER_SCHEMA,
            allowed_tools=("offer_search",), max_tool_calls=3, context=context))
        for t in outcome.tool_calls:
            ctx.events.tool_activity("researcher", t.call_id, t.tool_name, t.provider,
                                     "started", None, f"Iniciando {t.tool_name}")
            ctx.events.tool_activity("researcher", t.call_id, t.tool_name, t.provider,
                                     t.status, t.duration_ms, t.summary)
        offers, dropped = parse_offers(outcome.structured) if outcome.ok else ([], 0)
        marks = tuple(filtered_mark(f) for f in filters)  # registra o filtro pedido; não é prova
        return outcome, [replace(o, tags=o.tags + marks) for o in offers], dropped

    def _search_extras(self, ctx: AgentContext, origin: str, offers: list[Offer],
                       limitations: list[str]) -> dict[str, int]:
        """Uma busca por complemento (ex.: 'coca zero'); as ofertas entram marcadas em `extra_of`."""
        found: dict[str, int] = {}
        known = {o.product_id for o in offers}
        for extra in ctx.state.extra_terms:
            prompt = (f"Pedido do cliente: {ctx.session.message_text}\nProduto desejado: {extra}. Use somente "
                      "estes termos na query da busca e ordene por relevância.")
            outcome, extra_offers, _ = self._search(ctx, prompt, [])
            if not outcome.ok or origin_of(outcome) != origin:
                limitations.append(f"busca do complemento '{extra}' indisponível")
                continue
            found[extra] = len(extra_offers)
            for o in extra_offers:
                if o.product_id in known:  # já veio na busca do prato (ex.: combo com fritas): continua prato
                    continue
                ctx.state.extra_of[o.product_id] = extra
                offers.append(o)
                known.add(o.product_id)
        found.update(self._extras_in_restaurants(ctx, origin, offers, known))
        return found

    def _extras_in_restaurants(self, ctx: AgentContext, origin: str, offers: list[Offer],
                               known: set[str]) -> dict[str, int]:
        """Complemento que a busca geral não trouxe do restaurante do prato: procura DENTRO dos restaurantes
        mais aderentes ao prato (`merchant_id`), para o pedido sair inteiro de uma loja só."""
        st = ctx.state
        main = [o for o in offers if o.product_id not in st.extra_of and o.is_open is not False]
        best: dict[str, int] = {}  # soma: restaurante com vários itens do prato (pizzaria) antes de um item solto
        for o in main:
            best[o.merchant_id] = best.get(o.merchant_id, 0) + score(o, st.query_terms)
        ranked = sorted(best, key=lambda m: (-best[m], m))[:EXTRA_RESTAURANTS]
        has = {(o.merchant_id, st.extra_of[o.product_id]) for o in offers if o.product_id in st.extra_of}
        found: dict[str, int] = {}
        calls = 0
        for merchant in ranked:
            name = next(o.merchant_name for o in main if o.merchant_id == merchant)
            for extra in st.extra_terms:
                if (merchant, extra) in has or calls >= MAX_EXTRA_STORE_SEARCHES:
                    continue
                calls += 1
                prompt = (f"Pedido do cliente: {ctx.session.message_text}\nProduto desejado: {extra}. Use somente "
                          "estes termos na query da busca e ordene por relevância.")
                outcome, got, _ = self._search(ctx, prompt, [], {"merchant_id": merchant})
                if not outcome.ok or origin_of(outcome) != origin:
                    continue
                got = [o for o in got if o.merchant_id == merchant]
                for o in got:
                    if o.product_id not in known:
                        st.extra_of[o.product_id] = extra
                        offers.append(o)
                        known.add(o.product_id)
                found[f"{extra} em {name}"] = len(got)
        if calls:
            ctx.events.agent_message("researcher", "curator", ctx.task_id, "request",
                                     f"Procurei os complementos dentro de {len(ranked)} restaurante(s) do prato "
                                     f"({calls} busca(s)) para o pedido sair de uma loja só")
        return found

    def _run_groceries(self, ctx: AgentContext) -> AgentResult:
        """Uma busca por item da lista em mercados; depois, os itens que faltam DENTRO do mercado que mais
        cobriu a lista (cesta num só mercado = uma entrega)."""
        st = ctx.state
        offers: list[Offer] = []
        known: set[str] = set()
        origin: str | None = None
        limitations: list[str] = []
        failure: RuntimeOutcome | None = None

        def search(item: Any, scope: dict[str, str]) -> None:
            nonlocal origin, failure
            prompt = (f"Pedido do cliente: {ctx.session.message_text}\nProduto desejado: {item.name}. Use somente "
                      "estes termos na query da busca e ordene por relevância.\nCompra de supermercado"
                      + (f"; tamanho pedido: {item.note}" if item.note else "") + ".")
            outcome, found, _ = self._search(ctx, prompt, [], {"merchant_type": GROCERIES, **scope})
            if not outcome.ok:
                failure = failure or outcome
                limitations.append(f"busca de '{item.name}' indisponível")
                return
            got = origin_of(outcome)
            if origin is None:
                origin = got
            if got != origin:
                limitations.append(f"busca de '{item.name}' com origem divergente descartada")
                return
            for o in found:
                st.grocery_of.setdefault(o.product_id, item.name)
                if o.product_id not in known:
                    offers.append(o)
                    known.add(o.product_id)

        for item in st.shopping_list:
            search(item, {})
        if origin is None and failure is not None:
            return AgentResult("researcher", "error", {"error": failure.error, "detail": failure.detail,
                                                       "retry_after_s": failure.retry_after_s},
                               f"Falha do runtime: {failure.error}", limitations=[f"runtime:{failure.error}"])
        if ctx.session.mode == "real" and origin != "ifood_mcp":
            return AgentResult("researcher", "error", {"error": "unverified_origin"},
                               "Sessão real sem chamada MCP comprovada; resultado descartado.",
                               limitations=["origem não verificada"])
        coverage: dict[str, set[str]] = {}
        for o in offers:
            if o.is_open is not False:
                coverage.setdefault(o.merchant_id, set()).add(st.grocery_of[o.product_id])
        if coverage:
            preferred = st.preferred_merchant_id if st.preferred_merchant_id in coverage else None
            best = preferred or max(coverage, key=lambda m: (len(coverage[m]), m))
            missing = [i for i in st.shopping_list if i.name not in coverage[best]][:MAX_STORE_SEARCHES]
            if missing:
                name = next(o.merchant_name for o in offers if o.merchant_id == best)
                ctx.events.agent_message("researcher", "grocery_basket", ctx.task_id, "request",
                                         f"{name} cobre {len(coverage[best])} de {len(st.shopping_list)} itens; "
                                         f"procurando lá: {', '.join(i.name for i in missing)}")
            for item in missing:
                search(item, {"merchant_id": best})
        st.offers, st.data_origin = offers, (origin or "demo")  # type: ignore[assignment]
        if not offers:
            return AgentResult("researcher", "needs_info", {"offers": 0},
                               "Nenhum produto de mercado encontrado.", "low", limitations, ["ofertas disponíveis"])
        merchants = {o.merchant_id for o in offers}
        ctx.events.agent_message("researcher", "grocery_basket", ctx.task_id, "proposal",
                                 f"Trouxe {len(offers)} produto(s) de {len(merchants)} mercado(s) para "
                                 f"{len(st.shopping_list)} item(ns) da lista; pode montar a cesta?")
        return AgentResult(
            "researcher", "done", {"offers": len(offers), "merchants": len(merchants), "origin": st.data_origin},
            f"{len(offers)} produto(s) de {len(merchants)} mercado(s) para {len(st.shopping_list)} item(ns); "
            f"origem {st.data_origin}.", "high" if st.data_origin == "ifood_mcp" else "medium", limitations)

    def run(self, ctx: AgentContext) -> AgentResult:
        if ctx.state.shopping_list:
            return self._run_groceries(ctx)
        c = ctx.state.constraints
        terms = ctx.state.query_terms
        product = (f"Produto desejado: {' '.join(terms)}. Use somente estes termos na query da busca, "
                   "sem quantidade de pessoas nem orçamento, e ordene por relevância, não só por preço.\n"
                   if terms else "")
        summary = ctx.state.request_summary
        prompt = (f"Pedido do cliente: {ctx.session.message_text}\n"
                  + (f"Pedido entendido: {summary}\n" if summary else "") + product
                  + f"Orçamento (centavos): {c.budget_cents}; pessoas: {c.party_size}; "
                  f"restrições: {[restriction_label(r) for r in c.dietary]}; preferências: {list(c.preferences)}.")
        base_filters = dietary_filters(c)
        outcome, offers, dropped = self._search(ctx, prompt, base_filters)
        if not outcome.ok:
            return AgentResult("researcher", "error", {"error": outcome.error, "detail": outcome.detail,
                                                "retry_after_s": outcome.retry_after_s},
                               f"Falha do runtime: {outcome.error}",
                               limitations=[f"runtime:{outcome.error}"])
        origin = origin_of(outcome)
        if ctx.session.mode == "real" and origin != "ifood_mcp":
            return AgentResult("researcher", "error", {"error": "unverified_origin"},
                               "Sessão real sem chamada MCP comprovada; resultado descartado.",
                               limitations=["origem não verificada"])
        limitations = [f"{dropped} oferta(s) inválida(s) descartada(s)"] if dropped else []
        extra = [SOFT_FILTERS[r] for r in option_requirements(c) if r in SOFT_FILTERS]
        if VEGETARIAN_OPTION in c.dietary and VEGETARIAN_ALL not in c.dietary:
            extra.append("VEGETARIAN")
        for flt in dict.fromkeys(extra):
            # "uma opção vegetariana/vegana": busca extra com filtro só para escolher esse item.
            veg_outcome, veg_offers, _ = self._search(ctx, prompt, sorted(set(base_filters) | {flt}))
            if veg_outcome.ok and origin_of(veg_outcome) == origin:
                by_id = {o.product_id: o for o in offers}
                for o in veg_offers:
                    known = by_id.get(o.product_id)
                    by_id[o.product_id] = replace(known, tags=tuple(dict.fromkeys(known.tags + o.tags))) \
                        if known else o
                offers = list(by_id.values())
            else:
                limitations.append(f"busca adicional com filtro {flt} indisponível")
        found_extras = self._search_extras(ctx, origin, offers, limitations)
        ctx.state.offers, ctx.state.data_origin = offers, origin  # type: ignore[assignment]
        if not offers:
            return AgentResult("researcher", "needs_info", {"offers": 0},
                               "Nenhuma oferta válida encontrada.", "low", limitations,
                               ["ofertas disponíveis"])
        merchants = {o.merchant_id for o in offers}
        extra_note = "".join(f" + {n} de '{t}'" for t, n in found_extras.items())
        ctx.events.agent_message("researcher", "curator", ctx.task_id, "proposal",
                                 f"Trouxe {len(offers)} oferta(s) de '{' '.join(terms) or 'comida'}'{extra_note}; "
                                 "pode julgar se atendem ao pedido?")
        return AgentResult(
            "researcher", "done", {"offers": len(offers), "merchants": len(merchants), "origin": origin},
            f"{len(offers)} oferta(s) de {len(merchants)} restaurante(s); origem {origin}.",
            "high" if origin == "ifood_mcp" else "medium", limitations)
