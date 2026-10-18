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
