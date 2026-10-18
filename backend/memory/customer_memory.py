"""Memória persistente do cliente: pedidos feitos ao bot em cada atendimento e padrões simples.

Implementa `CustomerMemoryPort`. Guarda só prato, quantidade, orçamento, atendimento e data — nada de
nome, contato ou endereço. Isolado por (tenant_id, client_id). Padrões por agregação simples, sem modelo.
"""
from __future__ import annotations

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
                       party_size: int | None, budget_cents: int | None) -> bool:
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
                (tenant_id, client_id, session_id, dish, party_size, budget_cents, _now()))
        return exists is None

    def profile(self, tenant_id: str, client_id: str) -> CustomerProfile | None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, dish, party_size, budget_cents, at FROM customer_requests "
                "WHERE tenant_id=? AND client_id=? ORDER BY at, rowid", (tenant_id, client_id)).fetchall()
        if not rows:
            return None
        sessions = {r[0] for r in rows}
        counts = Counter(dish for _, dish, *_ in {(r[0], r[1]) for r in rows})
        favorites = tuple(sorted(((d, n) for d, n in counts.items() if n >= 2), key=lambda dn: (-dn[1], dn[0])))
        per_person = [b // p for _, _, p, b, _ in rows if p and b]
        last = rows[-1]
        return CustomerProfile(
            client_id=client_id, requests=len(sessions), favorite_dishes=favorites,
            last_terms=tuple(last[1].split()), last_party_size=last[2], last_budget_cents=last[3],
            last_at=last[4], typical_budget_per_person_cents=int(statistics.median(per_person)) if per_person else None)

    def forget(self, tenant_id: str, client_id: str) -> int:
        with self._lock, self._conn:
            return self._conn.execute(
                "DELETE FROM customer_requests WHERE tenant_id=? AND client_id=?", (tenant_id, client_id)).rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
