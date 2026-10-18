"""Catálogo FICTÍCIO para demonstração offline. Nenhum item, preço ou restaurante é real."""
from __future__ import annotations

from typing import Any


def _m(mid: str, name: str, fee: int, eta: int) -> dict[str, Any]:
    return {"merchant_id": mid, "merchant_name": name, "delivery_fee_cents": fee,
            "other_fees_cents": 0, "eta_minutes": eta}


_PIZZA = _m("demo_pizzaria", "Pizzaria Forno Demo", 790, 45)
_BURGER = _m("demo_burger", "Burger House Demo", 590, 35)
_SUSHI = _m("demo_sushi", "Sushi Zen Demo", 990, 50)
_VEG = _m("demo_verde", "Cozinha Verde Demo", 490, 30)
_BR = _m("demo_brasil", "Sabor Caseiro Demo", 0, 40)

# `keywords` serve só para a busca simulada e não sai no resultado.
DEMO_CATALOG: list[dict[str, Any]] = [
    {**_PIZZA, "product_id": "dp1", "name": "Pizza Margherita", "unit_price_cents": 4990,
     "tags": ["vegetarian"], "keywords": ["pizza", "margherita", "italiana", "jantar"]},
    {**_PIZZA, "product_id": "dp2", "name": "Pizza Calabresa", "unit_price_cents": 4790,
     "tags": [], "keywords": ["pizza", "calabresa", "italiana", "jantar"]},
    {**_PIZZA, "product_id": "dp3", "name": "Pizza Portuguesa", "unit_price_cents": 5490,
     "tags": [], "keywords": ["pizza", "portuguesa", "italiana", "jantar"]},
    {**_PIZZA, "product_id": "dp4", "name": "Pizza de Abobrinha e Rúcula", "unit_price_cents": 5290,
     "tags": ["vegetarian", "vegan"], "keywords": ["pizza", "vegana", "italiana", "jantar"]},
    {**_BURGER, "product_id": "db1", "name": "Smash Burger Clássico", "unit_price_cents": 3290,
     "tags": [], "keywords": ["hamburguer", "burger", "lanche", "smash"]},
    {**_BURGER, "product_id": "db2", "name": "Burger de Grão-de-Bico", "unit_price_cents": 3190,
     "tags": ["vegetarian", "vegan"], "keywords": ["hamburguer", "burger", "lanche", "vegano"]},
    {**_BURGER, "product_id": "db3", "name": "Cheese Bacon Duplo", "unit_price_cents": 3990,
     "tags": [], "keywords": ["hamburguer", "burger", "lanche", "bacon"]},
    {**_SUSHI, "product_id": "ds1", "name": "Combinado 20 peças", "unit_price_cents": 6990,
     "tags": [], "keywords": ["sushi", "japonesa", "japones", "combinado"]},
    {**_SUSHI, "product_id": "ds2", "name": "Yakisoba de Legumes", "unit_price_cents": 3890,
     "tags": ["vegetarian"], "keywords": ["japonesa", "japones", "yakisoba", "macarrao"]},
    {**_SUSHI, "product_id": "ds3", "name": "Temaki Salmão", "unit_price_cents": 2990,
     "tags": ["gluten-free"], "keywords": ["sushi", "japonesa", "japones", "temaki"]},
    {**_VEG, "product_id": "dv1", "name": "Bowl de Quinoa", "unit_price_cents": 3490,
     "tags": ["vegetarian", "vegan", "gluten-free"], "keywords": ["salada", "bowl", "saudavel", "leve"]},
    {**_VEG, "product_id": "dv2", "name": "Lasanha de Berinjela", "unit_price_cents": 3990,
     "tags": ["vegetarian", "gluten-free"], "keywords": ["lasanha", "massa", "jantar", "almoco"]},
    {**_VEG, "product_id": "dv3", "name": "Salada Caesar Vegana", "unit_price_cents": 2890,
     "tags": ["vegetarian", "vegan"], "keywords": ["salada", "saudavel", "leve"]},
    {**_BR, "product_id": "dc1", "name": "PF de Frango Grelhado", "unit_price_cents": 2790,
     "tags": ["gluten-free"], "keywords": ["frango", "marmita", "almoco", "prato", "comida"]},
    {**_BR, "product_id": "dc2", "name": "Feijoada Individual", "unit_price_cents": 3590,
     "tags": ["gluten-free"], "keywords": ["feijoada", "almoco", "prato", "comida", "carne"]},
    {**_BR, "product_id": "dc3", "name": "Strogonoff de Cogumelos", "unit_price_cents": 3290,
     "tags": ["vegetarian"], "keywords": ["strogonoff", "almoco", "jantar", "prato", "comida"]},
    {**_BR, "product_id": "dc4", "name": "Escondidinho de Mandioca e Legumes", "unit_price_cents": 3190,
     "tags": ["vegetarian", "gluten-free"], "keywords": ["escondidinho", "almoco", "jantar", "prato", "comida"]},
    {**_BR, "product_id": "dc5", "name": "Moqueca de Banana-da-Terra", "unit_price_cents": 3690,
     "tags": ["vegetarian", "vegan", "gluten-free"], "keywords": ["moqueca", "almoco", "jantar", "prato", "comida"]},
]


# ---- supermercados FICTÍCIOS (busca com merchant_type=GROCERIES) ----------------------------
_BOMPRECO = _m("demo_mercado_1", "Mercado Bom Preço Demo", 799, 60)
_ECONOMICO = _m("demo_mercado_2", "Super Econômico Demo", 1290, 90)
_HORTI = _m("demo_horti", "Hortifruti Fresco Demo", 590, 40)


def _g(merchant: dict[str, Any], pid: str, name: str, price: int, keywords: list[str],
       tags: list[str] | None = None) -> dict[str, Any]:
    return {**merchant, "product_id": pid, "name": name, "unit_price_cents": price, "tags": tags or [],
            "keywords": keywords}


DEMO_GROCERY_CATALOG: list[dict[str, Any]] = [
    _g(_BOMPRECO, "gm1", "Arroz Branco Tipo 1 5kg", 2899, ["arroz"]),
    _g(_BOMPRECO, "gm2", "Feijão Carioca 1kg", 849, ["feijao", "feijão"]),
    _g(_BOMPRECO, "gm3", "Leite Integral 1L", 549, ["leite", "leites"]),
    _g(_BOMPRECO, "gm4", "Leite Zero Lactose 1L", 699, ["leite", "leites", "lactose"], ["lactose-free"]),
    _g(_BOMPRECO, "gm5", "Doce de Leite 400g", 1190, ["leite", "doce"]),
    _g(_BOMPRECO, "gm6", "Café Torrado e Moído 500g", 1999, ["cafe", "café"]),
    _g(_BOMPRECO, "gm7", "Açúcar Refinado 1kg", 529, ["acucar", "açúcar"]),
    _g(_BOMPRECO, "gm8", "Ovos Brancos 12 unidades", 1290, ["ovo", "ovos"]),
    _g(_BOMPRECO, "gm9", "Detergente Líquido 500ml", 279, ["detergente"]),
    _g(_BOMPRECO, "gm10", "Papel Higiênico 12 rolos", 2290, ["papel", "higienico", "higiênico"]),
    _g(_ECONOMICO, "ge1", "Arroz Branco 1kg", 619, ["arroz"]),
    _g(_ECONOMICO, "ge2", "Feijão Carioca 1kg", 789, ["feijao", "feijão"]),
    _g(_ECONOMICO, "ge3", "Leite Integral 1L", 499, ["leite", "leites"]),
    _g(_ECONOMICO, "ge4", "Café Tradicional 500g", 1849, ["cafe", "café"]),
    _g(_ECONOMICO, "ge5", "Cerveja Lata 350ml", 399, ["cerveja"]),
    _g(_ECONOMICO, "ge6", "Frango Inteiro Congelado kg", 1190, ["frango"]),
    _g(_HORTI, "gh1", "Banana Prata kg", 699, ["banana"]),
    _g(_HORTI, "gh2", "Tomate Italiano kg", 899, ["tomate"]),
    _g(_HORTI, "gh3", "Ovos Caipira 12 unidades", 1690, ["ovo", "ovos"]),
]
