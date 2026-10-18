"""Runtime SIMULADO para demonstração offline. Implementa `AgentRuntimePort` sem rede.

Busca por palavras-chave do pedido no catálogo fictício e respeita `context.dietary_filters`.
Tudo sai com `provider="demo"`, então nunca é apresentado como dado real do iFood.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from ..models import slug
from ..ports import RuntimeCall, RuntimeOutcome, ToolTrace
from .catalog import DEMO_CATALOG

# Palavras genéricas não restringem a busca: "quero comida" deve ver o catálogo inteiro.
_GENERIC = {"comida", "prato", "jantar", "janta", "almoco", "refeicao"}
_FILTER_TAG = {"VEGETARIAN": "vegetarian", "VEGAN": "vegan", "GLUTEN_FREE": "gluten-free"}


def _customer_text(prompt: str) -> str:
    m = re.search(r"Pedido do cliente:\s*(.*)", prompt)
    return slug(m.group(1) if m else prompt)


class DemoCatalogRuntime:
    """`with_tags=False` imita o iFood real, que não devolve tags comprobatórias de dieta.
    `fail` força uma falha (`quota`, `timeout`, `unavailable`...) para demonstrar o tratamento."""

    def __init__(self, with_tags: bool = True, fail: str | None = None, fail_detail: str | None = None) -> None:
        self.with_tags, self.fail, self.fail_detail = with_tags, fail, fail_detail
        self.calls: list[RuntimeCall] = []

    def run(self, call: RuntimeCall) -> RuntimeOutcome:
        self.calls.append(call)
        if self.fail:
            return RuntimeOutcome(ok=False, error=self.fail, retry_after_s=30,  # type: ignore[arg-type]
                                  detail=self.fail_detail)
        text = _customer_text(call.prompt)
        words = set(text.split("-"))
        hits = [i for i in DEMO_CATALOG
                if any(slug(k) in words or slug(k) in text for k in i["keywords"] if slug(k) not in _GENERIC)]
        items = hits or DEMO_CATALOG
        for f in call.context.get("dietary_filters") or []:
            tag = _FILTER_TAG.get(f)
            if tag:
                items = [i for i in items if tag in i["tags"]]
        offers: list[dict[str, Any]] = []
        for item in items:
            offer = {k: copy.deepcopy(v) for k, v in item.items() if k != "keywords"}
            if not self.with_tags:  # imita o iFood real: sem tags de dieta nem taxa de serviço
                offer["tags"] = []
                offer["other_fees_cents"] = None
            offers.append(offer)
        trace = ToolTrace("demo_call", "offer_search", "demo", "succeeded", 5,
                          f"Busca SIMULADA: {len(offers)} oferta(s) do catálogo fictício")
        return RuntimeOutcome(ok=True, structured={"offers": offers}, tool_calls=(trace,))
