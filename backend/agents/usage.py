"""Custo de IA por cliente: tokens e custo de cada chamada (informados pelo provedor) e o valor das vendas
aceitas no chat, para o gestor ver quanto da venda foi gasto com IA.

O custo em US$ vem do OpenCode. Câmbio e margem NÃO existem nos dados: são parâmetros configurados
(`APP_USD_BRL_RATE`, `APP_ASSUMED_MARGIN_BPS`) e saem identificados no relatório. Memória do processo.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

from .ports import AgentRuntimePort, RuntimeCall, RuntimeOutcome

DEFAULT_USD_BRL = 5.5  # parâmetro de demonstração, não é cotação do dia
DEFAULT_MARGIN_BPS = 3000  # margem suposta da política comercial DEMO (30%)


@dataclass
class _Client:
    label: str
    sessions: set[str] = field(default_factory=set)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    cost_usd: float = 0.0
    sales: int = 0
    sales_cents: int = 0
    fictitious_sessions: int = 0  # histórico FICTÍCIO da demonstração somado a este cliente


class UsageLedger:
    """Acumula consumo e vendas por (tenant, cliente). Cliente anônimo conta por atendimento."""

    def __init__(self, usd_brl: float | None = None, margin_bps: int | None = None) -> None:
        self.usd_brl = usd_brl if usd_brl is not None else float(os.getenv("APP_USD_BRL_RATE", DEFAULT_USD_BRL))
        self.margin_bps = margin_bps if margin_bps is not None else int(
            os.getenv("APP_ASSUMED_MARGIN_BPS", DEFAULT_MARGIN_BPS))
        self._owner: dict[str, tuple[str, str]] = {}  # session_id -> (tenant, chave do cliente)
        self._clients: dict[tuple[str, str], _Client] = {}
        self._lock = threading.Lock()

    def bind(self, session_id: str, tenant_id: str, client_key: str | None, label: str) -> None:
        key = (tenant_id, client_key or f"anon:{session_id}")
        with self._lock:
            self._owner[session_id] = key
            client = self._clients.setdefault(key, _Client(label))
            client.sessions.add(session_id)

    def add(self, session_id: str, outcome: RuntimeOutcome) -> None:
        usage = outcome.usage
        with self._lock:
            key = self._owner.get(session_id)
            if key is None:
                return
            client = self._clients[key]
            client.calls += 1
            if usage is not None:
                client.input_tokens += usage.input_tokens
                client.output_tokens += usage.output_tokens
                client.cache_tokens += usage.cache_read_tokens + usage.cache_write_tokens
                client.cost_usd += usage.cost_usd

    def seed(self, tenant_id: str, client_key: str, label: str, *, sessions: int, calls: int, input_tokens: int,
             output_tokens: int, cache_tokens: int, cost_usd: float, sales: int, sales_cents: int) -> None:
        """Histórico FICTÍCIO (clientes da demonstração), marcado em `fictitious_sessions`."""
        with self._lock:
            c = self._clients.setdefault((tenant_id, client_key), _Client(label))
            c.fictitious_sessions += sessions
            c.calls += calls
            c.input_tokens += input_tokens
            c.output_tokens += output_tokens
            c.cache_tokens += cache_tokens
            c.cost_usd += cost_usd
            c.sales += sales
            c.sales_cents += sales_cents

    def owner(self, session_id: str) -> tuple[str, str] | None:
        with self._lock:
            return self._owner.get(session_id)

    def add_sale(self, session_id: str, total_cents: int | None) -> None:
        with self._lock:
            key = self._owner.get(session_id)
            if key is None or not isinstance(total_cents, int):
                return
            self._clients[key].sales += 1
            self._clients[key].sales_cents += total_cents

    def session_cost_usd(self, session_id: str) -> float:
        with self._lock:
            key = self._owner.get(session_id)
            return self._clients[key].cost_usd if key else 0.0

    def report(self, tenant_id: str) -> dict[str, Any]:
        """Por cliente: tokens, custo de IA (US$ e R$), vendido, % da venda gasta com IA e lucro estimado."""
        with self._lock:
            rows = [self._row(c) for (tenant, _), c in self._clients.items() if tenant == tenant_id]
        rows.sort(key=lambda r: -r["ai_cost_usd_micros"])
        totals = {k: sum(r[k] for r in rows) for k in ("sessions", "fictitious_sessions", "ai_calls",
                                                       "input_tokens", "output_tokens",
                                                       "cache_tokens", "ai_cost_usd_micros", "ai_cost_cents",
                                                       "sales", "sales_cents")}
        totals.update(self._ratios(totals["ai_cost_cents"], totals["sales_cents"]))
        return {"usd_brl_rate": self.usd_brl, "assumed_margin_bps": self.margin_bps, "clients": rows,
                "totals": totals}

    def total_cost_cents(self, tenant_id: str) -> int:
        return self.report(tenant_id)["totals"]["ai_cost_cents"]

    def _ratios(self, cost_cents: int, sales_cents: int) -> dict[str, int | None]:
        if not sales_cents:
            return {"ai_cost_share_bps": None, "estimated_profit_cents": None}
        return {"ai_cost_share_bps": round(cost_cents * 10000 / sales_cents),
                "estimated_profit_cents": round(sales_cents * self.margin_bps / 10000) - cost_cents}

    def _row(self, c: _Client) -> dict[str, Any]:
        cost_cents = round(c.cost_usd * self.usd_brl * 100)
        return {"client_label": c.label, "sessions": len(c.sessions) + c.fictitious_sessions,
                "fictitious_sessions": c.fictitious_sessions, "ai_calls": c.calls,
                "input_tokens": c.input_tokens, "output_tokens": c.output_tokens, "cache_tokens": c.cache_tokens,
                "ai_cost_usd_micros": round(c.cost_usd * 1_000_000), "ai_cost_cents": cost_cents,
                "sales": c.sales, "sales_cents": c.sales_cents, **self._ratios(cost_cents, c.sales_cents)}


class MeteredRuntime:
    """Envolve o runtime: toda chamada de IA/busca dos agentes passa aqui e o consumo vai para o livro."""

    def __init__(self, inner: AgentRuntimePort, ledger: UsageLedger) -> None:
        self.inner, self.ledger = inner, ledger

    def run(self, call: RuntimeCall) -> RuntimeOutcome:
        outcome = self.inner.run(call)
        self.ledger.add(call.session_id, outcome)
        return outcome

    def __getattr__(self, name: str) -> Any:  # mantém extras do runtime real (ex.: recommendation_warnings)
        return getattr(self.inner, name)
