"""Guardas de busca e evidências efêmeras; não define um cardápio permitido.

Correspondência lexical conservadora, não prova semântica, de ingredientes ou
de disponibilidade. Não consulta rede, não faz substituições nem novas buscas.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .errors import InvalidOutputError

_MODIFICATIONS = re.compile(
    r"\b(?:sem|extra|adicional|adicionais|retirar|tirar|adicionar|acrescentar)\b"
)

AVAILABILITY_UNKNOWN = "Loja aberta e disponibilidade de entrega ainda não confirmadas."
OPEN_FILTERED = (
    "Consulta filtrada pelo iFood para lojas abertas naquele momento; "
    "entrega e disponibilidade precisam ser revalidadas antes de comprar."
)
DISTANCE_UNKNOWN = "Distância não informada; não foi confirmado qual restaurante é o mais próximo."
CUSTOMIZATION_UNKNOWN = (
    "Ingredientes e personalização não confirmados no cardápio. "
    "Preço do item base; adicionais não verificados não estão incluídos."
)
PUBLIC_LOCATION = "Busca em coordenadas públicas de teste; não confirma entrega no seu endereço."
CLOSED_TEST_ONLY = (
    "Restaurante fechado no momento da consulta; opção exibida somente para teste e "
    "indisponível para pedido."
)
CLOSED_TEST_TAG = "__closed_merchant_test_only__"


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()


@dataclass(frozen=True)
class SearchIntent:
    customer_text: str
    customization_requested: bool

    @classmethod
    def from_prompt(cls, prompt: str) -> SearchIntent:
        match = re.search(r"Pedido do cliente:\s*([^\n]+)", prompt)
        text = (match.group(1) if match else prompt.partition("\n")[0]).strip()
        if not text:
            raise InvalidOutputError("invalid_query", retryable=False)
        plain = normalized_text(text)
        # A IA de busca interpreta o pedido original. Linhas auxiliares como
        # ``Produto desejado`` podem vir de regras antigas dos agentes e não são
        # promovidas a uma segunda interpretação obrigatória nesta integração.
        return cls(text, bool(_MODIFICATIONS.search(plain)))


def select_matching_offers(
    offers: Sequence[dict[str, Any]],
    intent: SearchIntent,
) -> tuple[list[dict[str, Any]], int]:
    """Deduplica e alterna o catálogo antes do julgamento do Curador.

    Os itens não são descartados por nome aqui: a IA de busca escolhe a query e o
    Curador julga os resultados. A integração só valida o contrato e a evidência
    da ferramenta, sem tentar reinterpretar semanticamente o pedido.
    """
    del intent
    groups: dict[str, deque] = {}
    seen = set()
    for offer in offers:
        key = (offer["merchant_id"], offer["product_id"])
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault(offer["merchant_id"], deque()).append(offer)
    selected = []
    while any(groups.values()):
        for group in groups.values():
            if group:
                selected.append(group.popleft())
    return selected, 0


class SearchEvidenceStore:
    """Só avisos por sessão/produto, com TTL e limite; não é cache de catálogo.

    Não guarda prompt, endereço, credenciais ou payload bruto de MCP. A origem
    verificada vem da execução do runtime, nunca do texto gerado pelo modelo.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        ttl_seconds: float = 300,
        max_sessions: int = 256,
    ) -> None:
        if ttl_seconds <= 0 or max_sessions < 1:
            raise ValueError("TTL e limite de sessões devem ser positivos")
        self._clock, self._ttl, self._limit = clock, ttl_seconds, max_sessions
        self._sessions: OrderedDict[
            str,
            dict[tuple[str, str], tuple[float, tuple[str, ...], dict[str, Any]]],
        ] = OrderedDict()
        self._lock = threading.Lock()

    def record(
        self,
        session_id: str,
        offers: Sequence[Mapping[str, Any]],
        *,
        public_location: bool,
        customization: bool,
        only_open: bool = False,
    ) -> None:
        base_notes = [
            OPEN_FILTERED if only_open else AVAILABILITY_UNKNOWN,
            DISTANCE_UNKNOWN,
            CUSTOMIZATION_UNKNOWN,
        ]
        if public_location:
            base_notes.append(PUBLIC_LOCATION)
        # Sem schema oficial de complementos, até os não solicitados são desconhecidos.
        if customization:
            base_notes.append(
                "A personalização solicitada ainda precisa ser confirmada pelo restaurante."
            )
        with self._lock:
            now = self._clock()
            entries = self._sessions.pop(session_id, {})
            entries = {key: value for key, value in entries.items() if value[0] > now}
            for offer in offers:
                notes = list(base_notes)
                if CLOSED_TEST_TAG in offer.get("tags", ()):
                    notes[0] = CLOSED_TEST_ONLY
                distance_km = offer.get("distance_km")
                if isinstance(distance_km, (int, float)) and not isinstance(distance_km, bool):
                    notes[1] = f"Distância informada pelo iFood: {distance_km:.1f} km."
                details = {
                    "original_unit_price_cents": offer.get("original_unit_price_cents"),
                    "image_url": offer.get("image_url"),
                    "eta_min_minutes": offer.get("eta_min_minutes"),
                    "distance_km": distance_km,
                    "merchant_rating": offer.get("merchant_rating"),
                    "is_open": offer.get("_merchant_is_open", offer.get("is_open")),
                }
                entries[(offer["merchant_id"], offer["product_id"])] = (
                    now + self._ttl,
                    tuple(notes),
                    details,
                )
            self._sessions[session_id] = dict(list(entries.items())[-250:])
            while len(self._sessions) > self._limit:
                self._sessions.popitem(last=False)

    def recommendation_warnings(
        self,
        session_id: str,
        merchant_id: str,
        product_ids: Sequence[str],
    ) -> list[str]:
        with self._lock:
            entries = self._sessions.get(session_id, {})
            now = self._clock()
            notes = []
            for product_id in product_ids:
                value = entries.get((merchant_id, product_id))
                if value is None or value[0] <= now:
                    notes.append(
                        "Evidência da busca ausente ou vencida; revalide preço e disponibilidade."
                    )
                else:
                    notes.extend(value[1])
            return list(dict.fromkeys(notes))

    def recommendation_details(
        self,
        session_id: str,
        merchant_id: str,
        product_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Metadados verificados da busca; ausentes ou vencidos permanecem nulos."""

        with self._lock:
            entries = self._sessions.get(session_id, {})
            now = self._clock()
            found = []
            item_details: dict[str, dict[str, Any]] = {}
            for product_id in product_ids:
                value = entries.get((merchant_id, product_id))
                if value is None or value[0] <= now:
                    continue
                details = value[2]
                found.append(details)
                item_details[product_id] = {
                    "original_unit_price_cents": details.get("original_unit_price_cents"),
                    "image_url": details.get("image_url"),
                }
            merchant_details = {}
            for key in ("eta_min_minutes", "distance_km", "merchant_rating", "is_open"):
                values = [details.get(key) for details in found if details.get(key) is not None]
                merchant_details[key] = (
                    values[0] if values and all(v == values[0] for v in values) else None
                )
            return {**merchant_details, "items": item_details}
