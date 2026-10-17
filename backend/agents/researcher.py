"""Pesquisador: pede ofertas ao runtime (MCP via OpenCode) e valida o que volta."""
from __future__ import annotations

from typing import Any

from .models import AgentResult, Offer, SessionContext, WorkingState
from .ports import RuntimeCall, RuntimeOutcome
from .registry import AgentContext, AgentDefinition

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
                },
            },
        }
    },
}

SYSTEM = (
    "Você é o Pesquisador de um chatbot de compras. Use SOMENTE as ferramentas de busca "
    "autorizadas para listar ofertas reais. Não invente produtos nem preços; preços em centavos "
    "inteiros de BRL; use null para valores desconhecidos."
)


def _tool_context(session: SessionContext) -> dict[str, Any]:
    """Contexto estruturado mínimo para as ferramentas. Hoje: apenas `location`, se informada."""
    location = session.initial_context.get("location")
    return {"location": location} if location else {}


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
                eta_minutes=_int_or_none(item.get("eta_minutes"))))
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

    def run(self, ctx: AgentContext) -> AgentResult:
        c = ctx.state.constraints
        prompt = (f"Pedido do cliente: {ctx.session.message_text}\n"
                  f"Orçamento (centavos): {c.budget_cents}; pessoas: {c.party_size}; "
                  f"restrições: {list(c.dietary)}; preferências: {list(c.preferences)}.")
        outcome = ctx.runtime.run(RuntimeCall(
            agent_id="researcher", task_id=ctx.task_id, session_id=ctx.session.session_id,
            system=SYSTEM, prompt=prompt, output_schema=OFFER_SCHEMA,
            allowed_tools=("offer_search",), max_tool_calls=3,
            context=_tool_context(ctx.session)))
        for t in outcome.tool_calls:
            ctx.events.tool_activity("researcher", t.call_id, t.tool_name, t.provider,
                                     "started", None, f"Iniciando {t.tool_name}")
            ctx.events.tool_activity("researcher", t.call_id, t.tool_name, t.provider,
                                     t.status, t.duration_ms, t.summary)
        if not outcome.ok:
            return AgentResult("researcher", "error", {"error": outcome.error, "detail": outcome.detail},
                               f"Falha do runtime: {outcome.error}",
                               limitations=[f"runtime:{outcome.error}"])
        origin = origin_of(outcome)
        if ctx.session.mode == "real" and origin != "ifood_mcp":
            return AgentResult("researcher", "error", {"error": "unverified_origin"},
                               "Sessão real sem chamada MCP comprovada; resultado descartado.",
                               limitations=["origem não verificada"])
        offers, dropped = parse_offers(outcome.structured)
        ctx.state.offers, ctx.state.data_origin = offers, origin  # type: ignore[assignment]
        limitations = [f"{dropped} oferta(s) inválida(s) descartada(s)"] if dropped else []
        if not offers:
            return AgentResult("researcher", "needs_info", {"offers": 0},
                               "Nenhuma oferta válida encontrada.", "low", limitations,
                               ["ofertas disponíveis"])
        merchants = {o.merchant_id for o in offers}
        return AgentResult(
            "researcher", "done", {"offers": len(offers), "merchants": len(merchants), "origin": origin},
            f"{len(offers)} oferta(s) de {len(merchants)} restaurante(s); origem {origin}.",
            "high" if origin == "ifood_mcp" else "medium", limitations)
