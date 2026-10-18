"""Memória operacional temporária; substituível por qualquer MemoryPort.

Não possui banco, RAG ou persistência. Os dados somem ao reiniciar o processo.
"""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from backend.agents.ports import RevisionConflict, StateSnapshot


class EphemeralSessionMemory:
    def __init__(self) -> None:
        self._sessions: dict[str, tuple[dict[str, Any], int]] = {}
        self._lock = RLock()

    def load(self, session_id: str) -> StateSnapshot:
        with self._lock:
            state, revision = self._sessions.get(session_id, ({}, 0))
            return StateSnapshot(deepcopy(state), revision)

    def save_patch(
        self, session_id: str, patch: dict[str, Any], expected_revision: int, author: str
    ) -> int:
        del author
        with self._lock:
            state, revision = self._sessions.get(session_id, ({}, 0))
            if revision != expected_revision:
                raise RevisionConflict("A sessão foi atualizada por outra operação.")
            self._sessions[session_id] = ({**state, **deepcopy(patch)}, revision + 1)
            return revision + 1
