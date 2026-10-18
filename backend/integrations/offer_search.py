"""Implementação de demonstração da ferramenta lógica ``offer_search``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import uuid4

from .config import SandboxLocation
from .errors import InvalidOutputError, UnavailableError


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """Resultado interno de ferramenta usado para montar ``ToolTrace`` depois."""

    call_id: str
    tool_name: str
    provider: str
    status: str
    duration_ms: int
    output: dict[str, Any]


class DemoOfferSearch:
    """Busca determinística e explicitamente simulada para testes ponta a ponta."""

    logical_name = "offer_search"

    def __init__(self, location: SandboxLocation | None = None) -> None:
        self._location = location

    async def execute(self, arguments: Mapping[str, Any]) -> ToolExecution:
        started_at = monotonic()
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise InvalidOutputError("offer_search exige query não vazia")

        location = arguments.get("user_location")
        if location is None and self._location is None:
            raise UnavailableError(
                "localização de sandbox não configurada para offer_search",
                retryable=False,
            )

        max_price = _read_max_price(arguments)
        base_price = 4_990
        items: list[dict[str, Any]] = []
        if max_price is None or base_price <= max_price:
            items.append(
                {
                    "item_id": "demo_item_pizza_1",
                    "item_name": "Pizza marguerita de demonstração",
                    "image_url": None,
                    "unit_price_cents": base_price,
                    "promotional_price_cents": None,
                    "merchant_id": "demo_merchant_1",
                    "merchant_name": "Pizzaria Demonstração",
                    "merchant_rating": None,
                    "is_open": True,
                    "delivery_fee_cents": 599,
                    "estimated_minutes_min": 30,
                    "estimated_minutes_max": 45,
                    "distance_km": None,
                    "match_score": None,
                    "why_recommended": "Item fictício compatível com a busca de demonstração.",
                    "concerns": ["Resultado simulado; nenhuma consulta ao iFood foi realizada."],
                }
            )

        output = {
            "provider": "demo",
            "data_origin": "demo",
            "result_kind": "ITEM",
            "interpreted_query": query.strip(),
            "merchants": [],
            "items": items,
            "pagination": {"next_page_token": None, "has_more": False},
            "warnings": ["Dados de demonstração; não representam ofertas reais do iFood."],
        }
        return ToolExecution(
            call_id=f"demo_call_{uuid4().hex}",
            tool_name=self.logical_name,
            provider="demo",
            status="succeeded",
            duration_ms=max(0, round((monotonic() - started_at) * 1000)),
            output=output,
        )


def _read_max_price(arguments: Mapping[str, Any]) -> int | None:
    filters = arguments.get("filters")
    if filters is None:
        return None
    if not isinstance(filters, Mapping):
        raise InvalidOutputError("filters precisa ser um objeto")
    value = filters.get("max_item_price_cents")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidOutputError("max_item_price_cents precisa ser inteiro não negativo")
    return value
