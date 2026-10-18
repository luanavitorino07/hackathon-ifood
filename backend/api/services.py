"""Pontos de composição da API com autenticação, agentes e STT."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Iterator, Literal, Protocol

from fastapi import Request

from .models import Actor, AgentDefinition, ChatMessageRequest, SubmitOrderRequest


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    tenant_id: str
    subject_id: str
    role: Literal["customer", "admin"]


class IdentityResolver(Protocol):
    async def resolve(self, request: Request) -> RequestIdentity: ...


class DemoCustomerIdentityResolver:
    """Identidade fictícia fixa; adequada somente ao processo local de demo."""

    async def resolve(self, request: Request) -> RequestIdentity:
        del request
        return RequestIdentity(
            tenant_id="tenant_demo",
            subject_id="client_demo_1",
            role="customer",
        )


class DemoIdentityResolver(DemoCustomerIdentityResolver):
    """Perfis fictícios para demonstração local; não é autenticação real."""

    async def resolve(self, request: Request) -> RequestIdentity:
        if request.headers.get("x-demo-role") == "admin":
            return RequestIdentity("tenant_demo", "manager_demo_1", "admin")
        return await super().resolve(request)


@dataclass(frozen=True, slots=True)
class MessageDispatch:
    tenant_id: str
    client_id: str
    request: ChatMessageRequest
    mode: Literal["real", "demo"] = "demo"
    initial_context: dict[str, Any] | None = None


class MessageDispatcher(Protocol):
    async def dispatch(self, message: MessageDispatch) -> None: ...


class OrchestratorDispatcher:
    """Adapta a API para ``orchestrator.handle_message(SessionContext)``.

    A fábrica de ``SessionContext`` pertence ao módulo de agentes. Dessa forma,
    a API não duplica nem importa prematuramente os tipos ainda não publicados.
    """

    def __init__(
        self,
        orchestrator: Any,
        context_factory: Callable[[MessageDispatch], Any],
        event_sink: StateEventSink | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._context_factory = context_factory
        self._event_sink = event_sink
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def dispatch(self, message: MessageDispatch) -> None:
        lock = await self._session_lock(message.request.session_id)
        async with lock:
            context = self._context_factory(message)
            if self._event_sink is None:
                await asyncio.to_thread(self._orchestrator.handle_message, context)
                return
            identity = RequestIdentity(message.tenant_id, message.client_id, "customer")
            with self._event_sink.bind(identity):
                outcome = await asyncio.to_thread(self._orchestrator.handle_message, context)
            await self._event_sink.set_session_status(
                message.request.session_id,
                identity,
                outcome.session_status,
            )

    async def _session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._session_locks.setdefault(session_id, asyncio.Lock())


def build_session_context(message: MessageDispatch) -> Any:
    """Cria o tipo que pertence a ``backend.agents`` sem duplicá-lo na API."""

    models = import_module("backend.agents.models")
    return models.SessionContext(
        session_id=message.request.session_id,
        tenant_id=message.tenant_id,
        client_id=message.client_id,
        mode=message.mode,
        message_text=message.request.text,
        input_mode=message.request.input_mode,
        initial_context=message.initial_context,
    )


@dataclass(frozen=True, slots=True)
class _EventBinding:
    loop: asyncio.AbstractEventLoop
    identity: RequestIdentity


class StateEventSink:
    """Persiste eventos dos agentes no estado antes de liberar a execução."""

    def __init__(self, state: Any, *, timeout_seconds: float = 30.0) -> None:
        self._state = state
        self._timeout_seconds = timeout_seconds
        self._binding: ContextVar[_EventBinding | None] = ContextVar(
            "agent_event_binding", default=None
        )
        self.catalog_warning_lookup: Callable[[str, str, list[str]], list[str]] | None = None
        self._catalog_notes: ContextVar[tuple[str, ...]] = ContextVar("catalog_notes", default=())

    @contextmanager
    def bind(self, identity: RequestIdentity) -> Iterator[None]:
        binding = _EventBinding(asyncio.get_running_loop(), identity)
        token = self._binding.set(binding)
        notes_token = self._catalog_notes.set(())
        try:
            yield
        finally:
            self._catalog_notes.reset(notes_token)
            self._binding.reset(token)

    def emit(
        self,
        *,
        session_id: str,
        type: str,
        actor: dict[str, str],
        recipient: dict[str, str] | None,
        visibility: Literal["admin", "customer", "both"],
        payload: dict[str, Any],
    ) -> None:
        binding = self._binding.get()
        if binding is None:
            raise RuntimeError("StateEventSink precisa estar vinculado a uma mensagem")
        if type == "recommendations_ready" and self.catalog_warning_lookup is not None:
            # Enriquece apenas warnings do contrato v1; não muda preços nem o payload dos agentes.
            recommendations = []
            customer_notes = []
            for recommendation in payload["recommendations"]:
                notes = self.catalog_warning_lookup(
                    session_id,
                    recommendation["merchant_id"],
                    [item["product_id"] for item in recommendation["items"]],
                )
                customer_notes.extend(notes)
                recommendations.append(
                    {
                        **recommendation,
                        "warnings": list(dict.fromkeys(recommendation["warnings"] + notes)),
                    }
                )
            payload = {**payload, "recommendations": recommendations}
            self._catalog_notes.set(tuple(dict.fromkeys(customer_notes)))
        if type == "chat_message" and self._catalog_notes.get():
            message = payload["message"]
            if message["role"] == "assistant":
                payload = {
                    **payload,
                    "message": {
                        **message,
                        "text": message["text"]
                        + " Preço, disponibilidade e personalização precisam ser confirmados "
                        "antes de comprar.",
                    },
                }
        operation = self._state.publish_event(
            session_id=session_id,
            identity=binding.identity,
            event_type=type,
            actor=Actor.model_validate(actor),
            recipient=Actor.model_validate(recipient) if recipient is not None else None,
            visibility=visibility,
            payload=payload,
        )
        future = asyncio.run_coroutine_threadsafe(operation, binding.loop)
        future.result(timeout=self._timeout_seconds)

    async def set_session_status(
        self,
        session_id: str,
        identity: RequestIdentity,
        status: str,
    ) -> None:
        await self._state.set_session_status(session_id, identity, status)


class OrchestratorAgentCatalog:
    def __init__(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    async def list_agents(self) -> list[AgentDefinition]:
        raw = await asyncio.to_thread(self._orchestrator.catalog)
        return [AgentDefinition.model_validate(item) for item in raw]


@dataclass(frozen=True, slots=True)
class AgentServiceBundle:
    dispatcher: OrchestratorDispatcher
    catalog: OrchestratorAgentCatalog
    event_sink: StateEventSink
    orchestrator: Any
    memory: Any


def build_agent_services(*, runtime: Any, memory: Any, state: Any) -> AgentServiceBundle:
    """Compõe agentes com implementações externas sem editar o módulo deles."""

    bootstrap = import_module("backend.agents.bootstrap")
    event_sink = StateEventSink(state)
    orchestrator = bootstrap.build_orchestrator(runtime, memory, event_sink)
    return AgentServiceBundle(
        dispatcher=OrchestratorDispatcher(
            orchestrator,
            build_session_context,
            event_sink,
        ),
        catalog=OrchestratorAgentCatalog(orchestrator),
        event_sink=event_sink,
        orchestrator=orchestrator,
        memory=memory,
    )


def build_demo_agent_services(
    *, runtime: Any, state: Any, memory: Any | None = None
) -> AgentServiceBundle:
    """Compõe os agentes com memória temporária, sem acoplar sua persistência."""

    from .session_memory import EphemeralSessionMemory

    return build_agent_services(
        runtime=runtime,
        memory=memory if memory is not None else EphemeralSessionMemory(),
        state=state,
    )


class OrderDispatcher(Protocol):
    async def dispatch(self, request: SubmitOrderRequest, identity: RequestIdentity) -> None: ...


class AgentCatalogProvider(Protocol):
    async def list_agents(self) -> list[AgentDefinition]: ...


class EmptyAgentCatalog:
    async def list_agents(self) -> list[AgentDefinition]:
        return []


AsyncTask = Callable[[], Awaitable[None]]
