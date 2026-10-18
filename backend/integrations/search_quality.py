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

_SPELLINGS = {
    "parmigiana": "parmegiana",
    "hamburger": "hamburguer",
    "burger": "hamburguer",
    "burguer": "hamburguer",
    "hamburgueres": "hamburguer",
}
_MODIFICATIONS = re.compile(
    r"\b(?:sem|extra|adicional|adicionais|retirar|tirar|adicionar|acrescentar)\b"
)
_BASE_MODIFICATION = re.compile(
    r"\b(?:sem|extra|adicional|adicionais|retirar|tirar|adicionar|acrescentar)\b[^,;.]*"
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


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()


def _tokens(value: str) -> set[str]:
    return {_SPELLINGS.get(t, t) for t in re.findall(r"[a-z]+", normalized_text(value))}


@dataclass(frozen=True)
class SearchIntent:
    customer_text: str
    terms: frozenset[str]
    customization_requested: bool

    @classmethod
    def from_prompt(cls, prompt: str) -> SearchIntent:
        match = re.search(r"Pedido do cliente:\s*([^\n]+)", prompt)
        text = (match.group(1) if match else prompt.partition("\n")[0]).strip()
        if not text:
            raise InvalidOutputError("invalid_query", retryable=False)
        plain = normalized_text(text)
        # O pesquisador é dono da extração do prato. Não reinterpretar a conversa
        # com uma segunda lista de stopwords divergente da dos agentes.
        product = re.search(r"(?m)^Produto desejado:\s*([^.\n]+)", prompt)
        terms = _tokens(product.group(1)) if product else set()
        # Compatibilidade com o pesquisador anterior ao PR #8: ele ainda inclui
        # ingredientes a retirar nos termos. Não os exigir no nome do item base.
        modifications = " ".join(m.group(0) for m in _BASE_MODIFICATION.finditer(plain))
        terms -= _tokens(modifications)
        return cls(text, frozenset(terms), bool(_MODIFICATIONS.search(plain)))

    def validate_query(self, query: str) -> None:
        if not self.terms.issubset(_tokens(query)):
            # Detalhe já reconhecido pelos agentes; não mascara como falha OAuth.
            raise InvalidOutputError("invalid_query", retryable=False)

    def matches(self, name: str) -> bool:
        return self.terms.issubset(_tokens(name))


def select_matching_offers(
    offers: Sequence[dict[str, Any]],
    intent: SearchIntent,
) -> tuple[list[dict[str, Any]], int]:
    """Somente nomes compatíveis, sem substituir por pratos parecidos.

    Distribui por restaurante sem alterar preço, taxa ou inventar distância.
    Um único restaurante disponível continua sendo um único restaurante.
    """
    groups: dict[str, deque] = {}
    seen = set()
    mismatches = 0
    for offer in offers:
        if not intent.matches(offer["name"]):
            mismatches += 1
            continue
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
    return selected, mismatches


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
        self._sessions: OrderedDict[str, dict[tuple[str, str], tuple[float, tuple[str, ...]]]] = (
            OrderedDict()
        )
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
        notes = [
            OPEN_FILTERED if only_open else AVAILABILITY_UNKNOWN,
            DISTANCE_UNKNOWN,
            CUSTOMIZATION_UNKNOWN,
        ]
        if public_location:
            notes.append(PUBLIC_LOCATION)
        # Sem schema oficial de complementos, até os não solicitados são desconhecidos.
        if customization:
            notes.append(
                "A personalização solicitada ainda precisa ser confirmada pelo restaurante."
            )
        with self._lock:
            now = self._clock()
            entries = self._sessions.pop(session_id, {})
            entries = {key: value for key, value in entries.items() if value[0] > now}
            for offer in offers:
                entries[(offer["merchant_id"], offer["product_id"])] = (
                    now + self._ttl,
                    tuple(notes),
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
