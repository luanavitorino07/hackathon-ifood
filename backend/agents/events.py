"""Construção e validação (chaves fechadas, §15.4) dos eventos emitidos pelos agentes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .ports import EventSink

PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "chat_message": frozenset({"message"}),
    "agent_status": frozenset({"agent_id", "status", "task_id", "summary"}),
    "agent_message": frozenset({"message_id", "task_id", "channel", "summary"}),
    "tool_activity": frozenset(
        {"call_id", "tool_name", "provider", "status", "duration_ms", "summary"}
    ),
    "conflict_detected": frozenset({"conflict_id", "agent_ids", "description", "status"}),
    "decision_made": frozenset({"decision_id", "recommendation_id", "summary", "reasons", "limitations"}),
    "recommendations_ready": frozenset({"recommendations"}),
    "error": frozenset({"code", "message", "retryable"}),
    "knowledge_retrieved": frozenset({"query_id", "topics", "sources", "count"}),
    "memory_changed": frozenset({"scope", "keys", "summary"}),
    "pattern_identified": frozenset(
        {"pattern_id", "description", "basis", "evidence_count", "confidence"}),
    "order_status_changed": frozenset({"order_id", "status", "summary"}),
    "discount_proposed": frozenset(
        {"proposal_id", "recommendation_id", "discount_type", "discount_bps", "discount_cents",
         "estimated_profit_delta_cents", "status", "requires_approval", "reason"}),
}
CHANNELS = {"request", "proposal", "review", "resolution"}

ORCHESTRATOR_ID = "orchestrator"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def agent(agent_id: str) -> dict[str, str]:
    return {"kind": "agent", "id": agent_id}


class EventEmitter:
    """Valida o payload contra o contrato antes de entregar ao sink."""

    def __init__(self, sink: EventSink, session_id: str) -> None:
        self._sink = sink
        self._session_id = session_id

    def _emit(self, type_: str, actor: dict[str, str], recipient: dict[str, str] | None,
              visibility: str, payload: dict[str, Any]) -> None:
        if set(payload) != PAYLOAD_KEYS[type_]:
            raise ValueError(f"payload de '{type_}' fora do contrato: {sorted(payload)}")
        self._sink.emit(session_id=self._session_id, type=type_, actor=actor,
                        recipient=recipient, visibility=visibility, payload=payload)  # type: ignore[arg-type]

    def agent_status(self, agent_id: str, status: str, task_id: str | None, summary: str | None) -> None:
        self._emit("agent_status", agent(agent_id), None, "admin", {"agent_id": agent_id, "status": status, "task_id": task_id, "summary": summary})

    def agent_message(self, sender: str, recipient: str, task_id: str, channel: str, summary: str) -> None:
        if channel not in CHANNELS:
            raise ValueError(f"channel inválido: {channel}")
        self._emit("agent_message", agent(sender), agent(recipient), "admin",
                   {"message_id": new_id("agent_msg"), "task_id": task_id, "channel": channel, "summary": summary})

    def tool_activity(self, agent_id: str, call_id: str, tool_name: str, provider: str,
                      status: str, duration_ms: int | None, summary: str) -> None:
        self._emit("tool_activity", {"kind": "tool", "id": tool_name}, agent(agent_id), "admin",
                   {"call_id": call_id, "tool_name": tool_name, "provider": provider,
                    "status": status, "duration_ms": duration_ms, "summary": summary})

    def conflict(self, conflict_id: str, agent_ids: list[str], description: str, status: str) -> None:
        self._emit("conflict_detected", agent(ORCHESTRATOR_ID), None, "admin",
                   {"conflict_id": conflict_id, "agent_ids": agent_ids, "description": description,
                    "status": status})

    def decision(self, recommendation_id: str | None, summary: str, reasons: list[str],
                 limitations: list[str]) -> None:
        self._emit("decision_made", agent(ORCHESTRATOR_ID), None, "admin",
                   {"decision_id": new_id("dec"), "recommendation_id": recommendation_id,
                    "summary": summary, "reasons": reasons, "limitations": limitations})

    def recommendations_ready(self, recommendations: list[dict[str, Any]]) -> None:
        self._emit("recommendations_ready", agent(ORCHESTRATOR_ID), None, "both",
                   {"recommendations": recommendations})

    def assistant_message(self, text: str) -> None:
        message = {"message_id": new_id("msg"), "role": "assistant", "input_mode": "text",
                   "text": text, "created_at": utc_now()}
        self._emit("chat_message", agent(ORCHESTRATOR_ID), {"kind": "customer", "id": "customer"},
                   "both", {"message": message})

    def error(self, code: str, message: str, retryable: bool) -> None:
        self._emit("error", agent(ORCHESTRATOR_ID), None, "admin",
                   {"code": code, "message": message, "retryable": retryable})

    def knowledge_retrieved(self, agent_id: str, topics: list[str], sources: list[dict[str, str]]) -> None:
        self._emit("knowledge_retrieved", agent(agent_id), None, "admin",
                   {"query_id": new_id("kq"), "topics": topics, "sources": sources, "count": len(sources)})

    def pattern_identified(self, agent_id: str, description: str, basis: str, evidence_count: int,
                           confidence: str) -> None:
        self._emit("pattern_identified", agent(agent_id), None, "admin",
                   {"pattern_id": new_id("pat"), "description": description, "basis": basis,
                    "evidence_count": evidence_count, "confidence": confidence})

    def discount_proposed(self, agent_id: str, recommendation_id: str, discount_bps: int,
                          discount_cents: int, profit_delta_cents: int | None, reason: str) -> None:
        """Sempre `suggested` + `requires_approval`: sugerir não é aplicar."""
        self._emit("discount_proposed", agent(agent_id), None, "admin",
                   {"proposal_id": new_id("disc"), "recommendation_id": recommendation_id,
                    "discount_type": "percent", "discount_bps": discount_bps,
                    "discount_cents": discount_cents, "estimated_profit_delta_cents": profit_delta_cents,
                    "status": "suggested", "requires_approval": True, "reason": reason})

    def order_status(self, order_id: str | None, status: str, summary: str) -> None:
        self._emit("order_status_changed", agent(ORCHESTRATOR_ID), {"kind": "customer", "id": "customer"},
                   "both", {"order_id": order_id, "status": status, "summary": summary})

    def memory_changed(self, scope: str, keys: list[str], summary: str) -> None:
        self._emit("memory_changed", agent(ORCHESTRATOR_ID), None, "admin",
                   {"scope": scope, "keys": keys, "summary": summary})
