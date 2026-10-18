"""Pontos de composição da API com autenticação, agentes e STT."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import secrets
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Iterator, Literal, Protocol

from fastapi import Request

from backend.integrations.search_quality import CLOSED_TEST_ONLY

from .models import Actor, AgentDefinition, ChatMessageRequest, SubmitOrderRequest

logger = logging.getLogger(__name__)


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
    """Perfis fictícios para demonstração local; não é autenticação real.

    Em modo real, o papel administrativo só pode ser habilitado explicitamente e
    apenas em conexões realmente locais. Um cookie de sessão opaco permite que o
    ``EventSource`` do navegador preserve o papel depois de uma primeira chamada
    ``fetch`` com ``X-Demo-Role: admin``.
    """

    cookie_name = "ifood_local_demo_admin"

    def __init__(
        self,
        *,
        mode: Literal["real", "demo"] = "demo",
        allow_real_admin: bool = False,
        cookie_token: str | None = None,
    ) -> None:
        self._mode = mode
        self._allow_real_admin = allow_real_admin
        self._cookie_token = cookie_token or secrets.token_urlsafe(32)

    async def resolve(self, request: Request) -> RequestIdentity:
        # The local buyer and office share one browser cookie jar. An explicit
        # customer request must never inherit administrative event visibility.
        if request.headers.get("x-demo-role") == "customer":
            return await super().resolve(request)
        header_admin = request.headers.get("x-demo-role") == "admin"
        cookie_admin = hmac.compare_digest(
            request.cookies.get(self.cookie_name, ""),
            self._cookie_token,
        )
        if (header_admin or cookie_admin) and self._admin_is_allowed(request):
            if header_admin:
                request.state.issue_local_demo_admin_cookie = self._cookie_token
            return RequestIdentity("tenant_demo", "manager_demo_1", "admin")
        return await super().resolve(request)

    def _admin_is_allowed(self, request: Request) -> bool:
        if self._mode == "demo":
            return True
        return self._allow_real_admin and _is_loopback_request(request)


def _is_loopback_request(request: Request) -> bool:
    """Não confia em cabeçalhos de proxy para conceder o papel administrativo."""

    if request.client is None or not _is_loopback_host(request.client.host):
        return False
    hostname = request.url.hostname
    return hostname is not None and _is_loopback_host(hostname)


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


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

    async def run_due_schedules(self) -> int:
        """Compras agendadas que chegaram na data: os agentes refazem a cesta no atendimento de origem e
        pedem confirmação ao cliente (nada é comprado). Usa a mesma trava por sessão das mensagens."""
        due = getattr(self._orchestrator, "due_schedules", None)
        if due is None or self._event_sink is None:
            return 0
        ran = 0
        for schedule_id in await asyncio.to_thread(due):
            purchase = self._orchestrator.scheduled(schedule_id)
            if purchase is None or not purchase.client_id:
                continue
            lock = await self._session_lock(purchase.session_id)
            async with lock:
                identity = RequestIdentity(purchase.tenant_id, purchase.client_id, "customer")
                try:
                    with self._event_sink.bind(identity):
                        outcome = await asyncio.to_thread(self._orchestrator.run_schedule, schedule_id)
                    if outcome is not None:
                        await self._event_sink.set_session_status(
                            purchase.session_id, identity, outcome.session_status
                        )
                        ran += 1
                except Exception:  # sessão encerrada/expirada não derruba o relógio
                    logger.warning("compra agendada não executada", exc_info=True)
        return ran

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
        self.catalog_detail_lookup: (
            Callable[[str, str, list[str]], dict[str, Any]] | None
        ) = None
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
            # Enriquece apenas com evidência verificada da mesma busca; não aceita dados da IA.
            recommendations = []
            customer_notes = []
            for recommendation in payload["recommendations"]:
                product_ids = [item["product_id"] for item in recommendation["items"]]
                notes = self.catalog_warning_lookup(
                    session_id,
                    recommendation["merchant_id"],
                    product_ids,
                )
                details = (
                    self.catalog_detail_lookup(
                        session_id,
                        recommendation["merchant_id"],
                        product_ids,
                    )
                    if self.catalog_detail_lookup is not None
                    else {}
                )
                item_details = details.get("items", {})
                customer_notes.extend(notes)
                recommendations.append(
                    {
                        **recommendation,
                        "items": [
                            {**item, **item_details.get(item["product_id"], {})}
                            for item in recommendation["items"]
                        ],
                        "eta_min_minutes": details.get("eta_min_minutes"),
                        "distance_km": details.get("distance_km"),
                        "merchant_rating": details.get("merchant_rating"),
                        "is_open": details.get("is_open"),
                        "warnings": list(dict.fromkeys(recommendation["warnings"] + notes)),
                    }
                )
            payload = {**payload, "recommendations": recommendations}
            self._catalog_notes.set(tuple(dict.fromkeys(customer_notes)))
        if type == "chat_message" and self._catalog_notes.get():
            message = payload["message"]
            if message["role"] == "assistant":
                availability_notice = (
                    " Esta opção é somente para teste: o restaurante estava fechado no "
                    "momento da consulta e não está disponível para pedido."
                    if CLOSED_TEST_ONLY in self._catalog_notes.get()
                    else ""
                )
                payload = {
                    **payload,
                    "message": {
                        **message,
                        "text": message["text"]
                        + " Preço, disponibilidade e personalização precisam ser confirmados "
                        "antes de comprar."
                        + availability_notice,
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


class SimulatedOrderDispatcher:
    """Botão "Comprar": compra SIMULADA. Os agentes registram o pedido no atendimento e avisam o cliente;
    nada é enviado ao iFood e nenhum pagamento é feito (o MCP liberado só busca)."""

    simulated = True

    def __init__(self, orchestrator: Any, event_sink: StateEventSink, dispatcher: OrchestratorDispatcher) -> None:
        self._orchestrator, self._event_sink, self._dispatcher = orchestrator, event_sink, dispatcher

    async def dispatch(self, request: SubmitOrderRequest, identity: RequestIdentity) -> None:
        lock = await self._dispatcher._session_lock(request.session_id)  # mesma trava das mensagens
        async with lock:
            with self._event_sink.bind(identity):
                await asyncio.to_thread(self._orchestrator.simulate_purchase, request.session_id,
                                        request.recommendation_id, request.client_action_id)
            await self._event_sink.set_session_status(request.session_id, identity, "waiting_customer")


class OrchestratorUsageReport:
    """Custo de IA por cliente, calculado pelos agentes a partir do consumo informado pelo provedor."""

    def __init__(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    async def report(self, tenant_id: str) -> dict[str, Any] | None:
        report = getattr(self._orchestrator, "usage_report", None)
        return await asyncio.to_thread(report, tenant_id) if report is not None else None


@dataclass(frozen=True, slots=True)
class AgentServiceBundle:
    dispatcher: OrchestratorDispatcher
    catalog: OrchestratorAgentCatalog
    usage: OrchestratorUsageReport
    orders: SimulatedOrderDispatcher
    event_sink: StateEventSink
    orchestrator: Any
    memory: Any


def build_agent_services(*, runtime: Any, memory: Any, state: Any) -> AgentServiceBundle:
    """Compõe agentes com implementações externas sem editar o módulo deles."""

    bootstrap = import_module("backend.agents.bootstrap")
    event_sink = StateEventSink(state)
    orchestrator = bootstrap.build_orchestrator(runtime, memory, event_sink)
    dispatcher = OrchestratorDispatcher(orchestrator, build_session_context, event_sink)
    return AgentServiceBundle(
        dispatcher=dispatcher,
        orders=SimulatedOrderDispatcher(orchestrator, event_sink, dispatcher),
        catalog=OrchestratorAgentCatalog(orchestrator),
        usage=OrchestratorUsageReport(orchestrator),
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


class ScheduleTicker:
    """Relógio das compras agendadas: a cada ``interval_seconds`` roda as que venceram.

    Vive no processo da API (agendamentos ficam na memória do processo). ``interval_seconds <= 0`` desliga.
    """

    def __init__(self, dispatcher: OrchestratorDispatcher, interval_seconds: float = 30.0) -> None:
        self._dispatcher = dispatcher
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._dispatcher.run_due_schedules()
            except Exception:
                logger.warning("falha no relógio de compras agendadas", exc_info=True)
