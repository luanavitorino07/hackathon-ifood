"""Persistência do estado por sessão em SQLite. Implementa `MemoryPort` (backend/agents/ports.py).

Semântica acordada: sessão desconhecida -> `state={}`, `revision=0`; o patch substitui chaves de topo
(sem merge profundo); `None` grava `null`; revisão divergente levanta `RevisionConflict` sem gravar;
cada gravação incrementa a revisão em 1; comparação, gravação e auditoria são atômicas; `load` devolve
uma cópia independente; os valores só precisam ser serializáveis em JSON.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.agents.ports import RevisionConflict, StateSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_state (
    session_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    author TEXT NOT NULL,
    keys TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS state_audit_session ON state_audit (session_id, revision);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SQLiteMemory:
    """`path=":memory:"` para testes; um arquivo para persistir entre reinícios do processo."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        with self._lock:
            if str(path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)

    def load(self, session_id: str) -> StateSnapshot:
        with self._lock:
            row = self._conn.execute(
                "SELECT state, revision FROM session_state WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return StateSnapshot({}, 0)
        return StateSnapshot(json.loads(row[0]), int(row[1]))

    def save_patch(self, session_id: str, patch: dict[str, Any], expected_revision: int, author: str) -> int:
        if not isinstance(patch, dict):
            raise TypeError("patch precisa ser um dict")
        try:
            json.dumps(patch)
        except (TypeError, ValueError) as exc:
            raise ValueError("patch precisa ser serializável em JSON") from exc
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                row = cur.execute(
                    "SELECT state, revision FROM session_state WHERE session_id = ?", (session_id,)).fetchone()
                state, revision = (json.loads(row[0]), int(row[1])) if row else ({}, 0)
                if revision != expected_revision:
                    raise RevisionConflict(f"revisão esperada {expected_revision}, atual {revision}")
                new_revision = revision + 1
                now = _now()
                cur.execute(
                    "INSERT INTO session_state (session_id, state, revision, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET state = excluded.state, "
                    "revision = excluded.revision, updated_at = excluded.updated_at",
                    (session_id, json.dumps({**state, **patch}, ensure_ascii=False), new_revision, now))
                cur.execute(
                    "INSERT INTO state_audit (session_id, revision, author, keys, at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, new_revision, author, json.dumps(sorted(patch)), now))
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise
        return new_revision

    def audit(self, session_id: str) -> list[dict[str, Any]]:
        """Histórico interno de revisões (quem gravou quais chaves). Não contém os valores."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT revision, author, keys, at FROM state_audit WHERE session_id = ? ORDER BY revision",
                (session_id,)).fetchall()
        return [{"revision": r, "author": a, "keys": json.loads(k), "at": t} for r, a, k, t in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
