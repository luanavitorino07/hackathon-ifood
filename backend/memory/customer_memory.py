"""Memória persistente do cliente: pedidos feitos ao bot em cada atendimento e padrões simples.

Implementa `CustomerMemoryPort` e `StrategyOutcomePort`. Guarda só prato, quantidade, orçamento,
atendimento, data, restrições/preferências declaradas e o resultado das estratégias de venda — nada de
nome, contato ou endereço. Isolado por (tenant_id, client_id). Padrões por agregação simples, sem modelo.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.agents.ports import CustomerProfile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_requests (
    tenant_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    dish TEXT NOT NULL,
    party_size INTEGER,
    budget_cents INTEGER,
    at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, client_id, session_id, dish)
);
CREATE TABLE IF NOT EXISTS customer_profiles (
    tenant_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    restrictions TEXT NOT NULL DEFAULT '[]',
    preferences TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (tenant_id, client_id)
);
CREATE TABLE IF NOT EXISTS strategy_outcomes (
    tenant_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 0,
    total_cents INTEGER,
    at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, client_id, session_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SQLiteCustomerMemory:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def record_request(self, tenant_id: str, client_id: str, session_id: str, terms: tuple[str, ...],
                       party_size: int | None, budget_cents: int | None, at: str | None = None) -> bool:
        dish = " ".join(t for t in terms if t).strip()
        if not (tenant_id and client_id and session_id and dish):
            return False
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM customer_requests WHERE tenant_id=? AND client_id=? AND session_id=? AND dish=?",
                (tenant_id, client_id, session_id, dish)).fetchone()
            self._conn.execute(
                "INSERT INTO customer_requests VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, client_id, session_id, dish) DO UPDATE SET "
                "party_size=excluded.party_size, budget_cents=excluded.budget_cents, at=excluded.at",
                (tenant_id, client_id, session_id, dish, party_size, budget_cents, at or _now()))
        return exists is None

    def declare(self, tenant_id: str, client_id: str, restrictions: tuple[str, ...] = (),
                preferences: tuple[str, ...] = ()) -> None:
        """Cadastro do cliente: restrições e preferências declaradas (substitui as anteriores)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO customer_profiles VALUES (?, ?, ?, ?) ON CONFLICT(tenant_id, client_id) DO UPDATE SET "
                "restrictions=excluded.restrictions, preferences=excluded.preferences",
                (tenant_id, client_id, json.dumps(list(restrictions)), json.dumps(list(preferences))))

    def record_offer(self, tenant_id: str, client_id: str, session_id: str, strategy: str,
                     total_cents: int | None, accepted: bool = False, at: str | None = None) -> None:
        """Última oferta do atendimento e a estratégia usada (uma linha por atendimento)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO strategy_outcomes VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, client_id, session_id) DO UPDATE SET strategy=excluded.strategy, "
                "total_cents=excluded.total_cents, at=excluded.at",
                (tenant_id, client_id, session_id, strategy, int(accepted), total_cents, at or _now()))

    def record_acceptance(self, tenant_id: str, client_id: str, session_id: str) -> str | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT strategy FROM strategy_outcomes WHERE tenant_id=? AND client_id=? AND session_id=?",
                (tenant_id, client_id, session_id)).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE strategy_outcomes SET accepted=1 WHERE tenant_id=? AND client_id=? AND session_id=?",
                (tenant_id, client_id, session_id))
        return row[0]

    def strategy_performance(self, tenant_id: str, client_id: str | None = None) -> list[tuple[str, int, int]]:
        query = "SELECT strategy, COUNT(*), SUM(accepted) FROM strategy_outcomes WHERE tenant_id=?"
        args: tuple[str, ...] = (tenant_id,)
        if client_id is not None:
            query += " AND client_id=?"
            args += (client_id,)
        with self._lock:
            rows = self._conn.execute(query + " GROUP BY strategy ORDER BY strategy", args).fetchall()
        return [(r[0], r[1], r[2] or 0) for r in rows]

    def profile(self, tenant_id: str, client_id: str) -> CustomerProfile | None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, dish, party_size, budget_cents, at FROM customer_requests "
                "WHERE tenant_id=? AND client_id=? ORDER BY at, rowid", (tenant_id, client_id)).fetchall()
            declared = self._conn.execute(
                "SELECT restrictions, preferences FROM customer_profiles WHERE tenant_id=? AND client_id=?",
                (tenant_id, client_id)).fetchone()
        restrictions, preferences = (tuple(json.loads(declared[0])), tuple(json.loads(declared[1]))) \
            if declared else ((), ())
        stats = tuple(self.strategy_performance(tenant_id, client_id))
        if not rows:
            if not (declared or stats):
                return None
            return CustomerProfile(client_id, 0, (), (), None, None, None, None, restrictions, preferences, stats)
        sessions = {r[0] for r in rows}
        counts = Counter(dish for _, dish, *_ in {(r[0], r[1]) for r in rows})
        favorites = tuple(sorted(((d, n) for d, n in counts.items() if n >= 2), key=lambda dn: (-dn[1], dn[0])))
        per_person = [b // p for _, _, p, b, _ in rows if p and b]
        last = rows[-1]
        return CustomerProfile(
            client_id=client_id, requests=len(sessions), favorite_dishes=favorites,
            last_terms=tuple(last[1].split()), last_party_size=last[2], last_budget_cents=last[3],
            last_at=last[4], typical_budget_per_person_cents=int(statistics.median(per_person)) if per_person else None,
            declared_restrictions=restrictions, declared_preferences=preferences, strategy_stats=stats)

    def forget(self, tenant_id: str, client_id: str) -> int:
        with self._lock, self._conn:
            removed = self._conn.execute(
                "DELETE FROM customer_requests WHERE tenant_id=? AND client_id=?", (tenant_id, client_id)).rowcount
            for table in ("customer_profiles", "strategy_outcomes"):
                removed += self._conn.execute(
                    f"DELETE FROM {table} WHERE tenant_id=? AND client_id=?", (tenant_id, client_id)).rowcount
            return removed

    def close(self) -> None:
        with self._lock:
            self._conn.close()
