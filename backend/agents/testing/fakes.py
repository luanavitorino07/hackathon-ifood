"""SOMENTE PARA TESTES / DEMO. Nada aqui representa OpenCode, Gemini, MCP ou persistência reais.

Toda oferta devolvida por `FakeRuntime` sai com provider "demo", portanto nunca é
promovida a `ifood_mcp`.
"""
from __future__ import annotations

import copy
from typing import Any

from ..ports import RevisionConflict, RuntimeCall, RuntimeOutcome, StateSnapshot, ToolTrace

DEMO_OFFERS: list[dict[str, Any]] = [
    {"product_id": "dm_burger", "name": "Hambúrguer (DEMO)", "unit_price_cents": 2990,
     "merchant_id": "dm_rest_1", "merchant_name": "Lanchonete Demo", "tags": [],
     "delivery_fee_cents": 500, "other_fees_cents": 0, "eta_minutes": 35},
    {"product_id": "dm_veg", "name": "Burger vegetariano (DEMO)", "unit_price_cents": 2790,
     "merchant_id": "dm_rest_1", "merchant_name": "Lanchonete Demo", "tags": ["vegetarian"],
     "delivery_fee_cents": 500, "other_fees_cents": 0, "eta_minutes": 35},
    {"product_id": "dm_pizza", "name": "Pizza margherita (DEMO)", "unit_price_cents": 5990,
     "merchant_id": "dm_rest_2", "merchant_name": "Pizzaria Demo", "tags": ["vegetarian"],
     "delivery_fee_cents": 800, "other_fees_cents": 0, "eta_minutes": 50},
]


class FakeRuntime:
    """Runtime simulado. `error` força falha; `offers` substitui o catálogo demo."""

    def __init__(self, offers: list[dict[str, Any]] | None = None, error: str | None = None,
                 provider: str = "demo", detail: str | None = "falha simulada") -> None:
        self.offers = DEMO_OFFERS if offers is None else offers
        self.error, self.provider, self.detail = error, provider, detail
        self.calls: list[RuntimeCall] = []

    def run(self, call: RuntimeCall) -> RuntimeOutcome:
        self.calls.append(call)
        if self.error:
            return RuntimeOutcome(ok=False, error=self.error, retry_after_s=30,  # type: ignore[arg-type]
                                  detail=self.detail)
        trace = ToolTrace("call_demo_1", "offer_search", self.provider,  # type: ignore[arg-type]
                          "succeeded", 12, f"{len(self.offers)} oferta(s) simulada(s)")
        return RuntimeOutcome(ok=True, structured={"offers": copy.deepcopy(self.offers)}, tool_calls=(trace,))


class InMemoryMemory:
    def __init__(self) -> None:
        self._data: dict[str, tuple[dict[str, Any], int]] = {}

    def load(self, session_id: str) -> StateSnapshot:
        state, rev = self._data.get(session_id, ({}, 0))
        return StateSnapshot(copy.deepcopy(state), rev)

    def save_patch(self, session_id: str, patch: dict[str, Any], expected_revision: int, author: str) -> int:
        state, rev = self._data.get(session_id, ({}, 0))
        if rev != expected_revision:
            raise RevisionConflict(f"esperado {expected_revision}, atual {rev}")
        merged = {**state, **copy.deepcopy(patch)}
        self._data[session_id] = (merged, rev + 1)
        return rev + 1


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, *, session_id: str, type: str, actor: dict[str, str],
             recipient: dict[str, str] | None, visibility: str, payload: dict[str, Any]) -> None:
        self.events.append({"session_id": session_id, "type": type, "actor": actor,
                            "recipient": recipient, "visibility": visibility, "payload": payload})

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]
