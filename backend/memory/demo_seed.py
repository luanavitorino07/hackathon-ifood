"""Clientes FICTÍCIOS para a apresentação: cadastro, pedidos anteriores e resultado das estratégias.

Nada aqui vem de clientes reais, do iFood ou da empresa. Os nomes só existem no frontend (seletor de
cliente); a memória guarda a chave técnica derivada do nome (`persona_key`), nunca o nome.
Desligue com `APP_DEMO_CUSTOMERS=0`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.agents.models import persona_key

DEMO_CLIENT_ID = "client_demo_1"  # identidade técnica do cliente na API de demonstração
DEMO_TENANT_ID = "tenant_demo"

# (prato, pessoas, orçamento em reais, dias atrás, estratégia usada, aceitou)
PERSONAS: list[dict] = [
    {"name": "Ana Souza", "restrictions": ["vegetarian"], "preferences": ["comida japonesa"],
     "history": [("sushi vegetariano", 2, 120, 26, "favorito", True), ("poke", 2, 110, 18, "favorito", True),
                 ("sushi vegetariano", 2, 120, 9, "custo_beneficio", False), ("salada", 1, 50, 4, "saudavel", True),
                 ("poke", 2, 100, 2, "favorito", True)]},
    {"name": "Bruno Lima", "restrictions": [], "preferences": ["pizza de calabresa"],
     "history": [("pizza", 4, 150, 28, "premium", False), ("pizza", 4, 150, 21, "custo_beneficio", True),
                 ("hamburguer", 2, 80, 15, "premium", False), ("pizza", 4, 140, 8, "custo_beneficio", True),
                 ("pizza", 4, 150, 1, "custo_beneficio", True)]},
    {"name": "Carla Mendes", "restrictions": ["lactose-free"], "preferences": ["comida leve"],
     "history": [("acai", 1, 40, 25, "saudavel", True), ("salada", 1, 45, 17, "saudavel", True),
                 ("acai", 1, 40, 10, "novidade", False), ("poke", 1, 55, 3, "saudavel", True)]},
    {"name": "Diego Rocha", "restrictions": [], "preferences": ["hambúrguer artesanal"],
     "history": [("hamburguer", 1, 60, 27, "premium", True), ("hamburguer", 1, 60, 19, "premium", True),
                 ("hamburguer", 1, 55, 12, "favorito", True), ("pizza", 2, 90, 6, "novidade", False),
                 ("hamburguer", 1, 60, 2, "premium", True)]},
]

# Outros clientes fictícios, só para a monitoria de estratégias ter volume: (estratégia, oferecidas, aceitas)
OTHER_OUTCOMES = [("favorito", 18, 12), ("custo_beneficio", 22, 13), ("premium", 14, 5),
                  ("novidade", 9, 3), ("saudavel", 11, 7)]


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_demo_customers(memory, tenant_id: str = DEMO_TENANT_ID, client_id: str = DEMO_CLIENT_ID) -> int:
    """Carrega os clientes fictícios (idempotente). Devolve quantos atendimentos foram registrados."""
    count = 0
    for persona in PERSONAS:
        key = persona_key(client_id, persona["name"])
        memory.declare(tenant_id, key, tuple(persona["restrictions"]), tuple(persona["preferences"]))
        for n, (dish, party, budget, days, strategy, accepted) in enumerate(persona["history"]):
            session = f"seed_{key[-6:]}_{n}"
            memory.record_request(tenant_id, key, session, tuple(dish.split()), party, budget * 100, _ago(days))
            memory.record_offer(tenant_id, key, session, strategy, budget * 90, accepted, _ago(days))
            count += 1
    for strategy, offered, accepted in OTHER_OUTCOMES:
        for n in range(offered):
            memory.record_offer(tenant_id, f"seed_other_{strategy}", f"seed_{strategy}_{n}", strategy,
                                4000 + 500 * (n % 9), n < accepted, _ago(1 + n % 28))
    return count
