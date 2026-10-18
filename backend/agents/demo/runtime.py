"""Runtime SIMULADO para demonstração offline. Implementa `AgentRuntimePort` sem rede.

Busca por palavras-chave do pedido no catálogo fictício e respeita `context.dietary_filters`.
Tudo sai com `provider="demo"`, então nunca é apresentado como dado real do iFood.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from ..models import slug
from ..ports import RuntimeCall, RuntimeOutcome, ToolTrace
from .catalog import DEMO_CATALOG, DEMO_GROCERY_CATALOG

# Palavras genéricas não restringem a busca: "quero comida" deve ver o catálogo inteiro.
_GENERIC = {"comida", "prato", "jantar", "janta", "almoco", "refeicao"}
_FILTER_TAG = {"VEGETARIAN": "vegetarian", "VEGAN": "vegan", "GLUTEN_FREE": "gluten-free"}


def _customer_text(prompt: str) -> str:
    m = re.search(r"Pedido do cliente:\s*(.*)", prompt)
    product = re.search(r"Produto desejado:\s*([^.\n]*)", prompt)
    return slug((m.group(1) if m else prompt) + (" " + product.group(1) if product else ""))


_CONFIRM = re.compile(r"^(sim|fechado|fechou|pode ser|confirmo|confirma|quero esse|quero essa|bora|manda)\b")


def _json_after(label: str, prompt: str) -> Any:
    m = re.search(label + r":\s*(.*)", prompt)
    try:
        return json.loads(m.group(1)) if m else None
    except ValueError:
        return None


def _simulated_reasoning(call: RuntimeCall) -> RuntimeOutcome:
    """IA SIMULADA para a demo offline (regras simples, marcadas como demo). Não é um modelo real."""
    trace = (ToolTrace("demo_ia", "raciocinio_ia", "demo", "succeeded", 1, "IA SIMULADA (demo)"),)
    if call.agent_id == "interpreter":  # entende por regras e devolve no formato da IA
        from ..chat import classify
        from ..relevance import food_terms
        m = re.search(r"MENSAGEM:\s*(.*)", call.prompt)
        text = m.group(1).strip() if m else ""
        shown = "ULTIMA_SUGESTAO: nenhuma" not in call.prompt
        plain = slug(text).replace("-", " ")
        intent = ("confirmar" if shown and _CONFIRM.search(plain) else
                  "pedido" if classify(text, shown) == "order" else "conversa")
        terms = food_terms(text)
        return RuntimeOutcome(ok=True, tool_calls=trace, structured={
            "intencao": intent, "busca": " ".join(terms[:3]) or None, "pessoas": None, "orcamento_reais": None,
            "restricoes": [], "preferencias": (_json_after("ESTADO", call.prompt) or {}).get("preferencias") or [],
            "resumo": f"{text} (IA simulada)", "resposta": None,
            "conflito_com_perfil": None})
    if call.agent_id == "curator":
        terms = [slug(t) for t in _json_after("PRATO_JSON", call.prompt) or []]
        items = _json_after("ITENS_JSON", call.prompt) or []
        wanted = [r.get("id") for r in _json_after("RESTRICOES_JSON", call.prompt) or [] if isinstance(r, dict)]
        judged = []
        for it in items:
            text = slug(f"{it.get('item', '')} {it.get('restaurante', '')}").replace("burger", "burger-hamburguer")
            fit = "sim" if not terms or all(t[:5] in text for t in terms) else (
                "parcial" if any(t[:5] in text for t in terms) else "nao")
            tags = next((set(i["tags"]) for i in DEMO_CATALOG if i["product_id"] == it.get("product_id")), set())
            if "vegan" in tags:
                tags.add("vegetarian")
            judged.append({"product_id": it.get("product_id", ""), "fit": fit,
                           "reason": "corresponde ao pedido (simulado)" if fit == "sim" else "outro prato (simulado)",
                           "atende_restricoes": [r for r in wanted if r in tags]})
        return RuntimeOutcome(ok=True, structured={"items": judged}, tool_calls=trace)
    if call.agent_id == "grocery_basket":  # julga pelas palavras e acerta o pacote pelo tamanho pedido
        wanted = {i.get("id"): i for i in _json_after("LISTA_JSON", call.prompt) or [] if isinstance(i, dict)}
        restrictions = [r.get("id") for r in _json_after("RESTRICOES_JSON", call.prompt) or [] if isinstance(r, dict)]
        judged = []
        for p in _json_after("PRODUTOS_JSON", call.prompt) or []:
            item = wanted.get(p.get("item_id")) or {}
            words = [w for w in slug(item.get("item", "")).split("-") if len(w) >= 3]
            name = slug(p.get("produto", ""))
            first = name.split("-")[0] if name else ""
            fit = ("sim" if words and all(w[:5] in name for w in words) and first[:4] == words[0][:4] else
                   "parcial" if any(w[:5] in name for w in words) and first[:4] == words[0][:4] else "nao")
            qty = item.get("quantidade") or 1
            size = re.search(r"(\d+)", item.get("detalhe") or "")
            pack = re.search(r"(?:^|-)(\d+)kg", name)
            if size and pack:
                qty = max(1, int(size.group(1)) // int(pack.group(1)))
            tags = next((set(i["tags"]) for i in DEMO_GROCERY_CATALOG if i["product_id"] == p.get("product_id")), set())
            violates = [r for r in restrictions if r == "lactose-free" and "leite" in name and r not in tags]
            judged.append({"product_id": p.get("product_id", ""), "fit": fit, "quantidade": qty,
                           "motivo": "corresponde ao item (simulado)" if fit == "sim" else "outro produto (simulado)",
                           "viola_restricoes": violates, "atende_restricoes": []})
        return RuntimeOutcome(ok=True, structured={"produtos": judged}, tool_calls=trace)
    if call.agent_id == "sales_strategist":
        options = _json_after("OPCOES_JSON", call.prompt) or []
        client = _json_after("CLIENTE_JSON", call.prompt) or {}
        liked = [slug(x.split(" (")[0]) for x in (client.get("preferencias_declaradas") or [])
                 + (client.get("pratos_favoritos") or []) + (client.get("padroes_identificados") or [])
                 + [client.get("ultimo_pedido") or ""] if x]
        def matches(o: dict) -> bool:
            text = slug(" ".join(o.get("itens", [])) + " " + o.get("restaurante", ""))
            return any(w[:5] in text for t in liked for w in t.split("-") if w)
        ordered = sorted(options, key=lambda o: not matches(o))  # estável: preço continua desempate
        hit = bool(ordered) and matches(ordered[0])
        return RuntimeOutcome(ok=True, tool_calls=trace, structured={
            "estrategia": "favorito" if hit else "custo_beneficio", "precisa_incentivo": not hit,
            "ordem": [o.get("id", "") for o in ordered],
            "argumento": ("Separei esta porque combina com o que você gosta de pedir." if hit
                          else "Escolhi a opção com melhor custo-benefício para o seu pedido."),
            "motivo": ("IA simulada: priorizou a opção alinhada às preferências/histórico do cliente." if hit
                       else "IA simulada: nenhuma opção bate com o histórico; mantida a de melhor preço.")})
    if call.agent_id == "discount_specialist":
        m = re.search(r"MAXIMO_BPS:\s*(\d+)", call.prompt)
        client = _json_after("CLIENTE_JSON", call.prompt) or {}
        known = bool(client.get("pratos_favoritos") or client.get("historico_demo") or client.get("ultimo_pedido"))
        return RuntimeOutcome(ok=True, tool_calls=trace, structured={
            "sugerir": True, "desconto_bps": int(m.group(1)) if m else 0,
            "motivo": ("IA simulada: pedido acima do mínimo da política; cliente com histórico, incentivo para fidelizar."
                       if known else "IA simulada: pedido acima do mínimo da política; incentivo para converter cliente novo.")})
    if call.agent_id == "orchestrator":
        m = re.search(r"RESPOSTA_BASE:\s*(.*)", call.prompt)
        if m:
            return RuntimeOutcome(ok=True, tool_calls=trace, structured={"resposta": "Boa! " + m.group(1).strip()})
    return RuntimeOutcome(ok=False, error="unavailable", detail="sem IA simulada", tool_calls=trace)


class DemoCatalogRuntime:
    """`with_tags=False` imita o iFood real, que não devolve tags comprobatórias de dieta.
    `fail` força uma falha (`quota`, `timeout`, `unavailable`...) para demonstrar o tratamento."""

    def __init__(self, with_tags: bool = True, fail: str | None = None, fail_detail: str | None = None) -> None:
        self.with_tags, self.fail, self.fail_detail = with_tags, fail, fail_detail
        self.calls: list[RuntimeCall] = []

    def run(self, call: RuntimeCall) -> RuntimeOutcome:
        if not call.allowed_tools:
            return _simulated_reasoning(call)
        self.calls.append(call)
        if self.fail:
            return RuntimeOutcome(ok=False, error=self.fail, retry_after_s=30,  # type: ignore[arg-type]
                                  detail=self.fail_detail)
        text = _customer_text(call.prompt)
        words = set(text.split("-"))
        if call.context.get("merchant_type") == "GROCERIES":  # mercado: só o produto desejado, sem catálogo inteiro
            product = re.search(r"Produto desejado:\s*([^.\n]*)", call.prompt)
            wanted = set(slug(product.group(1) if product else "").split("-")) - {""}
            items = [i for i in DEMO_GROCERY_CATALOG if wanted & {slug(k) for k in i["keywords"]}
                     and call.context.get("merchant_id") in (None, i["merchant_id"])]
            hits = items
        else:
            hits = [i for i in DEMO_CATALOG
                    if any(slug(k) in words or slug(k) in text for k in i["keywords"] if slug(k) not in _GENERIC)]
            items = hits or DEMO_CATALOG
            if call.context.get("merchant_id"):  # busca dentro de um restaurante
                items = [i for i in hits if i["merchant_id"] == call.context["merchant_id"]]
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
