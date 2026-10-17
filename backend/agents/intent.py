"""Extração determinística de restrições do texto (sem LLM). Preserva o que o cliente já informou."""
from __future__ import annotations

import re
import unicodedata

from .models import VEGETARIAN_ALL, VEGETARIAN_OPTION, Constraints

_NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
            "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def extract_constraints(text: str, known: Constraints) -> Constraints:
    t = _plain(text)
    budget = known.budget_cents
    if budget is None:
        m = re.search(r"(?:r\$\s*|ate\s+|de\s+)(\d+(?:[.,]\d{1,2})?)(?:\s*reais)?", t)
        if m and ("r$" in m.group(0) or "reais" in m.group(0) or "ate" in m.group(0)):
            budget = round(float(m.group(1).replace(",", ".")) * 100)
    party = known.party_size
    if party is None:
        m = re.search(r"(\d+|" + "|".join(_NUMBERS) + r")\s+(?:pessoas|pessoa)", t)
        if m:
            party = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1)]
    dietary = set(known.dietary)
    if "vegetarian" in t:
        dietary.add(VEGETARIAN_OPTION if re.search(r"(uma|1|alguma)\s+opcao", t) else VEGETARIAN_ALL)
    return Constraints(budget, party, tuple(sorted(dietary)), known.preferences)
