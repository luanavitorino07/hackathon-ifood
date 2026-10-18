"""Portas que o módulo de agentes CONSOME. Implementações pertencem a outros módulos.

- `AgentRuntimePort`: integração OpenCode/Gemini/MCP (backend/integrations, Lorenzo).
- `MemoryPort`: estado por atendimento (backend/memory).
- `EventSink`: persiste e transmite eventos (backend/integrations).

Nada aqui conhece HTTP, OpenCode, Gemini ou MCP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


# ---- runtime de IA / ferramentas -------------------------------------------------
@dataclass(frozen=True)
class RuntimeCall:
    agent_id: str
    task_id: str
    session_id: str
    system: str  # papel do agente
    prompt: str  # contexto mínimo, sem dados pessoais
    output_schema: dict[str, Any]  # JSON Schema da resposta
    allowed_tools: tuple[str, ...] = ()  # nomes lógicos; ex.: "offer_search"
    max_tool_calls: int = 3
    timeout_s: float = 60.0  # teto da chamada inteira; estouro => error="timeout"
    context: dict[str, Any] = field(default_factory=dict)  # só o mínimo estruturado p/ ferramentas (ex.: localização); sem PII desnecessária


@dataclass(frozen=True)
class ToolTrace:
    call_id: str
    tool_name: str
    provider: Literal["ifood_mcp", "internal", "demo"]
    status: Literal["succeeded", "failed"]
    duration_ms: int | None
    summary: str  # sem payload sensível


RuntimeError_ = Literal["quota", "timeout", "invalid_output", "unavailable"]


@dataclass(frozen=True)
class RuntimeOutcome:
    ok: bool
    structured: dict[str, Any] | None = None
    tool_calls: tuple[ToolTrace, ...] = ()
    error: RuntimeError_ | None = None
    retry_after_s: int | None = None
    detail: str | None = None  # motivo curto e sanitizado, só para diagnóstico controlado


@runtime_checkable
class AgentRuntimePort(Protocol):
    def run(self, call: RuntimeCall) -> RuntimeOutcome: ...


# ---- memória compartilhada --------------------------------------------------------
class RevisionConflict(Exception):
    """`save_patch` com `expected_revision` diferente da persistida."""


@dataclass(frozen=True)
class StateSnapshot:
    state: dict[str, Any] = field(default_factory=dict)
    revision: int = 0


@runtime_checkable
class MemoryPort(Protocol):
    def load(self, session_id: str) -> StateSnapshot: ...

    def save_patch(self, session_id: str, patch: dict[str, Any], expected_revision: int, author: str) -> int:
        """Mescla `patch` (chaves de topo substituídas) e devolve a nova revisão."""
        ...


# ---- eventos ----------------------------------------------------------------------
@runtime_checkable
class EventSink(Protocol):
    """O sink atribui event_id/seq/occurred_at/tenant_id/mode/schema_version e persiste
    antes de transmitir. O módulo de agentes só informa o que está abaixo."""

    def emit(
        self,
        *,
        session_id: str,
        type: str,
        actor: dict[str, str],
        recipient: dict[str, str] | None,
        visibility: Literal["admin", "customer", "both"],
        payload: dict[str, Any],
    ) -> None: ...


# ---- conhecimento comercial (RAG) ---------------------------------------------------
@dataclass(frozen=True)
class KnowledgeHit:
    document_id: str
    title: str
    excerpt: str  # trecho recuperado (texto do documento, nunca dado de cliente)
    score: float
    data: dict[str, Any] = field(default_factory=dict)  # parâmetros estruturados do trecho, se houver


@runtime_checkable
class KnowledgePort(Protocol):
    """Busca em documentos comerciais da empresa (políticas, estratégias). Implementação: backend/memory."""

    def search(self, tenant_id: str, query: str, topics: tuple[str, ...] = (), k: int = 3) -> list[KnowledgeHit]: ...


# ---- memória do cliente (entre atendimentos) ----------------------------------------
@dataclass(frozen=True)
class CustomerProfile:
    """Padrões calculados dos pedidos feitos ao bot em atendimentos anteriores (não são compras
    confirmadas). Sem dados pessoais: só prato, quantidade, orçamento e datas."""

    client_id: str
    requests: int  # atendimentos com pedido registrado
    favorite_dishes: tuple[tuple[str, int], ...]  # (prato, atendimentos) com 2+ ocorrências
    last_terms: tuple[str, ...]
    last_party_size: int | None
    last_budget_cents: int | None
    last_at: str | None  # ISO 8601 UTC
    typical_budget_per_person_cents: int | None
    declared_restrictions: tuple[str, ...] = ()  # cadastro do cliente (ex.: "lactose-free")
    declared_preferences: tuple[str, ...] = ()
    strategy_stats: tuple[tuple[str, int, int], ...] = ()  # (estratégia, oferecida, aceita) para este cliente


@runtime_checkable
class CustomerMemoryPort(Protocol):
    """Histórico autorizado por cliente. Implementação: backend/memory."""

    def record_request(self, tenant_id: str, client_id: str, session_id: str, terms: tuple[str, ...],
                       party_size: int | None, budget_cents: int | None) -> bool:
        """Registra o pedido do atendimento; True se é um pedido novo, False se só atualizou."""
        ...

    def profile(self, tenant_id: str, client_id: str) -> CustomerProfile | None: ...

    def forget(self, tenant_id: str, client_id: str) -> int:
        """Apaga o histórico do cliente (correção/remoção); devolve quantos registros saíram."""
        ...


@runtime_checkable
class StrategyOutcomePort(Protocol):
    """Opcional na memória do cliente: resultado das estratégias de venda (monitoria)."""

    def record_offer(self, tenant_id: str, client_id: str, session_id: str, strategy: str,
                     total_cents: int | None) -> None: ...

    def record_acceptance(self, tenant_id: str, client_id: str, session_id: str) -> str | None:
        """Marca como aceita a última oferta do atendimento; devolve a estratégia dela."""
        ...

    def strategy_performance(self, tenant_id: str) -> list[tuple[str, int, int]]:
        """(estratégia, oferecida, aceita) somando todos os clientes do tenant."""
        ...
