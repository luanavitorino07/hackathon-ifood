"""Pontos de composição da API com autenticação, agentes e STT."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fastapi import Request

from .models import AgentDefinition, ChatMessageRequest, SubmitOrderRequest


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


@dataclass(frozen=True, slots=True)
class MessageDispatch:
    tenant_id: str
    client_id: str
    request: ChatMessageRequest


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
    ) -> None:
        self._orchestrator = orchestrator
        self._context_factory = context_factory

    async def dispatch(self, message: MessageDispatch) -> None:
        context = self._context_factory(message)
        await self._orchestrator.handle_message(context)


class OrderDispatcher(Protocol):
    async def dispatch(
        self, request: SubmitOrderRequest, identity: RequestIdentity
    ) -> None: ...


class AgentCatalogProvider(Protocol):
    async def list_agents(self) -> list[AgentDefinition]: ...


class EmptyAgentCatalog:
    async def list_agents(self) -> list[AgentDefinition]:
        return []


AsyncTask = Callable[[], Awaitable[None]]
