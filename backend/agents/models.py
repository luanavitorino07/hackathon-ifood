"""Modelos de dados internos do módulo de agentes (somente biblioteca padrão).

Dinheiro sempre em centavos inteiros de BRL; desconhecido é `None`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["real", "demo"]
DataOrigin = Literal["ifood_mcp", "demo"]
Confidence = Literal["low", "medium", "high"]

# Restrições alimentares normalizadas.
VEGETARIAN_OPTION = "vegetarian_option"  # ao menos um item vegetariano no pedido
VEGETARIAN_ALL = "vegetarian"  # todos os itens vegetarianos


@dataclass(frozen=True)
class Constraints:
    budget_cents: int | None = None
    party_size: int | None = None
    dietary: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_cents": self.budget_cents,
            "party_size": self.party_size,
            "dietary": list(self.dietary),
            "preferences": list(self.preferences),
        }


@dataclass(frozen=True)
class SessionContext:
    """Entrada do orquestrador, montada pela API/memória a partir da sessão."""

    session_id: str
    tenant_id: str
    client_id: str | None
    mode: Mode
    message_text: str
    input_mode: Literal["text", "audio"] = "text"
    constraints: Constraints = Constraints()
    initial_context: dict[str, Any] = field(default_factory=dict)  # opaco; ver bootstrap


@dataclass(frozen=True)
class Offer:
    product_id: str
    name: str
    unit_price_cents: int
    merchant_id: str
    merchant_name: str
    tags: tuple[str, ...] = ()
    delivery_fee_cents: int | None = None
    other_fees_cents: int | None = None
    eta_minutes: int | None = None


@dataclass
class AgentResult:
    agent_id: str
    status: Literal["done", "needs_info", "error"]
    output: dict[str, Any]
    justification: str
    confidence: Confidence | None = None
    limitations: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)


@dataclass
class WorkingState:
    """Estado compartilhado do atendimento durante uma mensagem (espelhado na memória)."""

    constraints: Constraints
    offers: list[Offer] = field(default_factory=list)
    data_origin: DataOrigin = "demo"
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    approved_ids: list[str] = field(default_factory=list)
    issues: dict[str, list[str]] = field(default_factory=dict)
    missing_data: list[str] = field(default_factory=list)


@dataclass
class AgentsOutput:
    """Resultado final entregue à API. A resposta ao cliente também sai como evento."""

    session_status: Literal["active", "waiting_customer", "error"]
    reply_text: str
    recommendations: list[dict[str, Any]]
