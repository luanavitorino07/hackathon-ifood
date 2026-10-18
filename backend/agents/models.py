"""Modelos de dados internos do módulo de agentes (somente biblioteca padrão).

Dinheiro sempre em centavos inteiros de BRL; desconhecido é `None`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["real", "demo"]
DataOrigin = Literal["ifood_mcp", "demo"]
Confidence = Literal["low", "medium", "high"]

# Restrições normalizadas. Qualquer outra entrada de `dietary` é um slug que cada item
# do pedido precisa carregar como tag da oferta; sem essa tag a restrição NÃO é verificável.
VEGETARIAN_OPTION = "vegetarian_option"  # ao menos um item vegetariano no pedido
VEGETARIAN_ALL = "vegetarian"  # todos os itens vegetarianos
SPECIAL_RESTRICTIONS = frozenset({VEGETARIAN_OPTION, VEGETARIAN_ALL})


def slug(text: str) -> str:
    """Normaliza texto livre para comparação (sem acento, minúsculo, hífens)."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


# Restrições "brandas": o iFood só as aceita como filtro de busca, sem tag que as comprove
# na resposta. Sem tag nas ofertas, a recomendação sai marcada como NÃO verificada.
SOFT_FILTERS = {"vegetarian": "VEGETARIAN", "vegan": "VEGAN", "gluten-free": "GLUTEN_FREE"}


FILTERED_PREFIX = "filtered:"  # tag interna: item veio de uma busca com esse filtro (NÃO é prova)


def filtered_mark(filter_name: str) -> str:
    return FILTERED_PREFIX + filter_name


def _soft_key(restriction: str) -> str:
    return "vegetarian" if restriction in SPECIAL_RESTRICTIONS else restriction


def soft_unverified(constraints: "Constraints", offers: "list[Offer] | tuple[Offer, ...]") -> tuple[str, ...]:
    """Restrições brandas pedidas para as quais nenhuma oferta traz a tag comprobatória."""
    found = {slug(t) for o in offers for t in o.tags}
    keys = {_soft_key(d) for d in constraints.dietary if _soft_key(d) in SOFT_FILTERS}
    return tuple(sorted(k for k in keys if k not in found))


def dietary_filters(constraints: "Constraints") -> list[str]:
    """Filtros de busca (nomes do MCP) para as restrições brandas.

    "Uma opção vegetariana" NÃO filtra a busca inteira (todos os itens viriam vegetarianos);
    o planejador garante ao menos um item vegetariano.
    """
    return sorted({SOFT_FILTERS[_soft_key(d)] for d in constraints.dietary
                   if d != VEGETARIAN_OPTION and _soft_key(d) in SOFT_FILTERS})


def tag_requirements(constraints: "Constraints", offers: "list[Offer] | tuple[Offer, ...]" = ()) -> tuple[str, ...]:
    """Restrições que EXIGEM tag explícita no item: as não-brandas e as brandas comprováveis."""
    skip = set(soft_unverified(constraints, offers)) if offers else set()
    return tuple(d for d in constraints.dietary
                 if d not in SPECIAL_RESTRICTIONS and d not in skip)


@dataclass(frozen=True)
class Constraints:
    budget_cents: int | None = None
    party_size: int | None = None
    dietary: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> "Constraints":
        """Tolerante a estado ausente ou malformado vindo da memória."""
        if not isinstance(data, dict):
            return cls()

        def ints(v: Any) -> int | None:
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None

        def texts(v: Any) -> tuple[str, ...]:
            return tuple(x for x in v if isinstance(x, str) and x) if isinstance(v, list) else ()

        return cls(ints(data.get("budget_cents")), ints(data.get("party_size")),
                   texts(data.get("dietary")), texts(data.get("preferences")))

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
    initial_context: dict[str, Any] | None = None  # contrato v1: pode ser nulo


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
    is_open: bool | None = None  # None = a fonte não informou


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
    price_ceiling_cents: int | None = None  # pedido "mais barato": só vale o que custar menos que isto
    query_terms: tuple[str, ...] = ()  # prato pedido (ex.: "marmita", "parmegiana"); vazio = genérico
    relevance_miss: bool = False  # nenhuma oferta corresponde ao prato pedido
    customer_profile: Any = None  # CustomerProfile de atendimentos anteriores, se houver


@dataclass
class AgentsOutput:
    """Resultado final entregue à API. A resposta ao cliente também sai como evento."""

    session_status: Literal["active", "waiting_customer", "error"]
    reply_text: str
    recommendations: list[dict[str, Any]]
