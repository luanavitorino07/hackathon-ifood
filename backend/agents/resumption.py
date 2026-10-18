"""Retomada incremental: reaproveitar a pesquisa anterior do MESMO atendimento quando só mudou
quantidade de pessoas ou orçamento, em vez de buscar de novo no iFood.

A pesquisa é identificada por uma assinatura (prato, restrições alimentares, localização e modo) e
tem validade curta: preços e disponibilidade não ficam congelados até o fim do atendimento.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

from .models import Constraints, Offer, SessionContext
from .researcher import parse_offers

SEARCH_TTL_S = 300  # 5 minutos (igual à validade das evidências de busca da integração)
_REFRESH = re.compile(
    r"\b(atualiz|busca\w* de novo|procur\w* de novo|pesquis\w* de novo|busca\w* novamente|"
    r"procur\w* novamente|outras opc|mais opc|novas opc|outro restaurante|outros restaurantes)")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def wants_refresh(text: str) -> bool:
    return bool(_REFRESH.search(_plain(text)))


def signature(session: SessionContext, constraints: Constraints, terms: tuple[str, ...]) -> dict[str, Any]:
    """O que define a busca. Orçamento, quantidade e preferências NÃO entram: mudar só isso reaproveita."""
    location = (session.initial_context or {}).get("location")
    return {"terms": sorted(terms), "dietary": sorted(constraints.dietary),
            "location": location if isinstance(location, str) else None, "mode": session.mode}


def reusable_offers(stored: dict[str, Any], session: SessionContext, current_signature: dict[str, Any],
                    now: float | None = None) -> tuple[list[Offer], str, str] | None:
    """Ofertas da pesquisa anterior se ainda valem para este pedido; None se for preciso buscar.

    Devolve (ofertas, origem, motivo legível).
    """
    if wants_refresh(session.message_text):
        return None
    last = stored.get("last_search")
    if not isinstance(last, dict) or last.get("signature") != current_signature:
        return None
    at = last.get("at")
    age = (now if now is not None else time.time()) - at if isinstance(at, (int, float)) else None
    if age is None or age < 0 or age > SEARCH_TTL_S:
        return None
    origin = stored.get("data_origin")
    if origin not in ("ifood_mcp", "demo") or (session.mode == "real" and origin != "ifood_mcp"):
        return None
    offers, _ = parse_offers({"offers": stored.get("candidates")})
    if not offers:
        return None
    return offers, origin, f"{len(offers)} oferta(s) da pesquisa de {int(age // 60)} min atrás"
