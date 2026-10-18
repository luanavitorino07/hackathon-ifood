"""Guarda padrão dos agendamentos de compra: memória do processo (reiniciar a API apaga).

Implementa `SchedulePort`. Um banco persistente pode substituí-la sem mudar os agentes.
"""
from __future__ import annotations

import threading

from .ports import ScheduledPurchase


class InMemorySchedules:
    def __init__(self) -> None:
        self._items: dict[str, ScheduledPurchase] = {}
        self._lock = threading.Lock()

    def save(self, purchase: ScheduledPurchase) -> None:
        with self._lock:
            self._items[purchase.schedule_id] = purchase

    def get(self, schedule_id: str) -> ScheduledPurchase | None:
        with self._lock:
            return self._items.get(schedule_id)

    def list_for(self, tenant_id: str, client_key: str | None, session_id: str) -> list[ScheduledPurchase]:
        with self._lock:
            mine = [p for p in self._items.values() if p.tenant_id == tenant_id
                    and p.status in ("pending_confirmation", "active")
                    and (p.client_key == client_key if client_key else p.session_id == session_id)]
        return sorted(mine, key=lambda p: p.next_run_at)

    def due(self, now_iso: str) -> list[ScheduledPurchase]:
        with self._lock:
            ready = [p for p in self._items.values() if p.status == "active" and p.next_run_at <= now_iso]
        return sorted(ready, key=lambda p: p.next_run_at)
