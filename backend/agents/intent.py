"""Construção determinística (sem LLM) das restrições do atendimento.

Precedência, da mais fraca para a mais forte: `initial_context` (só na primeira vez) < estado salvo
na memória < `session.constraints` < o que o cliente disser explicitamente na mensagem.
Listas (restrições/preferências) apenas acumulam; nada é removido em silêncio.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .models import VEGETARIAN_ALL, VEGETARIAN_OPTION, Constraints, slug

_NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
            "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}
_VEGETARIAN_WORDS = ("vegetarian", "vegetarian_option")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _clean_list(value: Any) -> list[str]:
    return [x.strip() for x in value if isinstance(x, str) and x.strip()] if isinstance(value, list) else []


def _union(*groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for group in groups:
        for item in group:
            seen.setdefault(item, None)
    return tuple(seen)


def overlay(base: Constraints, top: Constraints) -> Constraints:
    """`top` vence onde tem valor; listas são unidas."""
    return Constraints(
        top.budget_cents if top.budget_cents is not None else base.budget_cents,
        top.party_size if top.party_size is not None else base.party_size,
        _union(base.dietary, top.dietary), _union(base.preferences, top.preferences))


def normalize_restriction(text: str) -> str:
    """'vegetariana' -> VEGETARIAN_ALL; vegana e sem glúten viram restrições brandas; o resto vira slug (exige tag)."""
    s = slug(text)
    if s.startswith("vegetarian"):
        return VEGETARIAN_ALL
    if s.startswith("vegan"):
        return "vegan"
    if "gluten" in s and any(w in s for w in ("sem", "free", "livre", "intoler", "celia")):
        return "gluten-free"
    if "lactose" in s or s.startswith("sem-leite"):
        return "lactose-free"
    if "acucar" in s or "diabet" in s:
        return "sugar-free"
    return s


def constraints_from_initial_context(initial_context: dict[str, Any] | None, base: Constraints) -> Constraints:
    """Usa só `preferences` e `restrictions`; `name`/`age`/`location` não entram aqui."""
    ic = initial_context or {}
    restrictions = [normalize_restriction(r) for r in _clean_list(ic.get("restrictions"))]
    return overlay(base, Constraints(None, None, tuple(r for r in restrictions if r),
                                     tuple(_clean_list(ic.get("preferences")))))


def extract_constraints(text: str, known: Constraints) -> Constraints:
    """Aplica o que o cliente disse AGORA; valores explícitos substituem os anteriores."""
    t = _plain(text)
    budget, party, dietary = known.budget_cents, known.party_size, set(known.dietary)
    m = re.search(r"(?:r\$\s*|\bate\s+)(\d+(?:[.,]\d{1,2})?)(?!\d|\s*pessoa)(?:\s*reais)?|(\d+(?:[.,]\d{1,2})?)\s*reais", t)
    if m:
        budget = round(float((m.group(1) or m.group(2)).replace(",", ".")) * 100)
    m = re.search(r"(\d+|" + "|".join(_NUMBERS) + r")\s+(?:pessoas|pessoa)", t)
    if not m:  # "feijoada pra 2", "pizza para dois" (sem a palavra pessoas; não confunde com valores)
        m = re.search(r"\b(?:pra|para)\s+(\d{1,2}|" + "|".join(_NUMBERS) + r")\b(?!\s*(?:reais|real|conto|pila|r\$|[.,]\d))", t)
    if m:
        party = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1)]
    if "vegetarian" in t:
        dietary -= set(_VEGETARIAN_WORDS)  # a última declaração do cliente define o tipo
        dietary.add(VEGETARIAN_OPTION if re.search(r"(uma|1|alguma)\s+opcao", t) else VEGETARIAN_ALL)
    if re.search(r"\blactose\b|\bintoleran\w* a lactose|\bsem leite\b", t):
        dietary.add("lactose-free")
    if re.search(r"\bsem gluten\b|\bceliac", t):
        dietary.add("gluten-free")
    return Constraints(budget, party, tuple(sorted(dietary)), known.preferences)


_CHEAPER = re.compile(r"\b(mais barat|mais em conta|mais economic|menos caro|mais simples|baratinh|mais acessivel)")


def wants_cheaper(text: str) -> bool:
    return bool(_CHEAPER.search(_plain(text)))


_REPEAT = re.compile(r"\b(o mesmo|a mesma|mesma coisa|mesmo pedido|o de sempre|de novo|repet\w*|"
                     r"igual (?:da|ao|a) ultim\w*)")


def wants_repeat(text: str) -> bool:
    """"Quero o mesmo", "de novo", "o de sempre": repetir o último pedido do cliente."""
    return bool(_REPEAT.search(_plain(text)))
