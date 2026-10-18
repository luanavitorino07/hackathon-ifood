"""Dados comerciais de DEMONSTRAÇÃO. Nada aqui vem da empresa, do iFood ou de clientes reais.

Usados só em sessões `mode="demo"` para ilustrar personalização e sugestão de desconto.
"""
from __future__ import annotations

from typing import Any

DEMO_POLICY: dict[str, Any] = {
    "document_id": "demo_policy_v1",
    "title": "Política comercial (DEMO)",
    "min_subtotal_cents": 8000,      # só sugere desconto em pedidos a partir de R$ 80
    "discount_bps": 500,             # 5%
    "max_discount_cents": 1500,      # teto de R$ 15
    "assumed_margin_bps": 3000,      # margem suposta de 30% (hipótese demo)
    "assumed_conversion_bps": (5000, 6500),  # 50% sem desconto -> 65% com desconto (hipótese demo)
}

# Histórico de compras fictício por client_id (o da identidade demo da API é client_demo_1).
DEMO_PURCHASE_HISTORY: dict[str, dict[str, Any]] = {
    "client_demo_1": {"favorite_terms": ["pizza"], "orders": 6,
                      "description": "Pediu pizza em 6 dos últimos 8 pedidos (histórico DEMO)"},
}


def expected_profit_delta(subtotal_cents: int, discount_cents: int) -> int:
    """Lucro esperado com desconto menos sem desconto, sob as hipóteses DEMO acima."""
    margin = subtotal_cents * DEMO_POLICY["assumed_margin_bps"] // 10000
    p0, p1 = DEMO_POLICY["assumed_conversion_bps"]
    return (p1 * (margin - discount_cents) - p0 * margin) // 10000
