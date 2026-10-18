"""Estado efêmero do MVP para contrato HTTP, projeções e histórico SSE."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from .errors import APIError
from .models import (
    Actor,
    AdminOverviewResponse,
    AgentRuntime,
    Cart,
    ChatAcceptedResponse,
    ChatMessage,
    ChatMessageRequest,
    EventType,
    HistoryResponse,
    Mode,
    OfficeEvent,
    OverviewMetrics,
    OverviewWindow,
    RecentSession,
    Recommendation,
    SessionCreateResponse,
    SessionSnapshotResponse,
    SessionStatus,
    SessionSummary,
    Visibility,
)
from .services import RequestIdentity

Audience = Literal["customer", "admin"]


@dataclass(slots=True)
class _SessionRecord:
    session_id: str
    tenant_id: str
    client_id: str
    client_alias: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    events: list[OfficeEvent] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    cart: Cart | None = None
    agents: dict[str, AgentRuntime] = field(default_factory=dict)
    accepted_messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    accepted_orders: dict[str, dict[str, Any]] = field(default_factory=dict)


class InMemoryBackendState:
    """Implementação de demo; pode ser substituída pelo repositório da memória."""

    def __init__(self) -> None:
        self._records: dict[str, _SessionRecord] = {}
        self._condition = asyncio.Condition()

    async def create_session(
        self,
        *,
        identity: RequestIdentity,
        client_id: str | None,
        mode: Mode = Mode.DEMO,
        initial_context: dict[str, Any] | None = None,
        memory: Any | None = None,
    ) -> SessionCreateResponse:
        if identity.role != "customer":
            raise APIError(403, "FORBIDDEN", "Apenas compradores podem criar sessões.")
        resolved_client_id = client_id or identity.subject_id
        if client_id is not None and client_id != identity.subject_id:
            raise APIError(403, "FORBIDDEN", "Cliente não autorizado.")

        now = _utcnow()
        async with self._condition:
            session_id = f"sess_{uuid4().hex}"
            if initial_context is not None:
                if memory is None:
                    raise APIError(503, "MEMORY_UNAVAILABLE", "A memória não está configurada.")
                await asyncio.to_thread(
                    memory.save_patch,
                    session_id,
                    {"initial_context": initial_context},
                    expected_revision=0,
                    author="api",
                )
            alias = f"Cliente #{len(self._records) + 1}"
            record = _SessionRecord(
                session_id=session_id,
                tenant_id=identity.tenant_id,
                client_id=resolved_client_id,
                client_alias=alias,
                mode=mode.value if isinstance(mode, Mode) else mode,
                status=SessionStatus.ACTIVE.value,
                created_at=now,
                updated_at=now,
            )
            self._records[session_id] = record
            self._append_event_locked(
                record,
                event_type=EventType.SESSION_STARTED,
                actor=Actor(kind="system", id="api"),
                recipient=None,
                visibility=Visibility.BOTH,
                payload={"client_alias": alias},
            )
            self._condition.notify_all()

        return SessionCreateResponse(
            session_id=session_id,
            client_alias=alias,
            mode=mode,
            status=SessionStatus.ACTIVE,
            created_at=now,
        )

    async def accept_message(
        self, request: ChatMessageRequest, identity: RequestIdentity
    ) -> ChatAcceptedResponse:
        response, _ = await self.accept_message_once(request, identity)
        return response

    async def accept_message_once(
        self, request: ChatMessageRequest, identity: RequestIdentity
    ) -> tuple[ChatAcceptedResponse, bool]:
        """Aceita atomicamente; só o primeiro envio deve agendar os agentes.

        O booleano é interno e não altera o DTO público HTTP. A garantia vale
        neste processo, assim como o restante de InMemoryBackendState.
        """
        async with self._condition:
            record = self._require_access_locked(request.session_id, identity)
            serialized = request.model_dump(mode="json")
            previous = record.accepted_messages.get(request.client_message_id)
            if previous is not None:
                if previous != serialized:
                    raise APIError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "client_message_id já foi usado com outro conteúdo.",
                    )
                return ChatAcceptedResponse(
                    session_id=request.session_id,
                    client_message_id=request.client_message_id,
                ), False

            record.accepted_messages[request.client_message_id] = serialized
            message = ChatMessage(
                message_id=request.client_message_id,
                role="customer",
                input_mode=request.input_mode,
                text=request.text,
                created_at=_utcnow(),
            )
            self._append_event_locked(
                record,
                event_type=EventType.CHAT_MESSAGE,
                actor=Actor(kind="customer", id=record.client_id),
                recipient=Actor(kind="system", id="orchestrator"),
                visibility=Visibility.BOTH,
                payload={"message": message.model_dump(mode="json")},
            )
            self._condition.notify_all()

        return ChatAcceptedResponse(
            session_id=request.session_id,
            client_message_id=request.client_message_id,
        ), True

    async def publish_event(
        self,
        *,
        session_id: str,
        identity: RequestIdentity,
        event_type: EventType | str,
        actor: Actor,
        recipient: Actor | None,
        visibility: Visibility | str,
        payload: dict[str, Any],
    ) -> OfficeEvent:
        async with self._condition:
            record = self._require_access_locked(session_id, identity)
            event = self._append_event_locked(
                record,
                event_type=EventType(event_type),
                actor=actor,
                recipient=recipient,
                visibility=Visibility(visibility),
                payload=payload,
            )
            self._condition.notify_all()
            return event

    async def snapshot(self, session_id: str, identity: RequestIdentity) -> SessionSnapshotResponse:
        async with self._condition:
            record = self._require_access_locked(session_id, identity)
            agents = list(record.agents.values()) if identity.role == "admin" else []
            return SessionSnapshotResponse(
                session=SessionSummary(
                    session_id=record.session_id,
                    client_alias=record.client_alias,
                    status=record.status,
                    mode=record.mode,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                ),
                last_seq=len(record.events),
                agents=agents,
                messages=list(record.messages),
                recommendations=list(record.recommendations),
                cart=record.cart,
            )

    async def history(
        self,
        session_id: str,
        identity: RequestIdentity,
        *,
        after_seq: int,
        limit: int,
    ) -> HistoryResponse:
        async with self._condition:
            record = self._require_access_locked(session_id, identity)
            matching = self._visible_events_locked(record, identity.role, after_seq)
            selected = matching[:limit]
            last_seq = selected[-1].seq if selected else after_seq
            return HistoryResponse(
                session_id=session_id,
                events=selected,
                last_seq=last_seq,
                has_more=len(matching) > len(selected),
            )

    async def wait_for_events(
        self,
        session_id: str,
        identity: RequestIdentity,
        *,
        after_seq: int,
        timeout_seconds: float,
    ) -> list[OfficeEvent]:
        async with self._condition:
            record = self._require_access_locked(session_id, identity)
            events = self._visible_events_locked(record, identity.role, after_seq)
            if events:
                return events
            try:
                await asyncio.wait_for(self._condition.wait(), timeout=timeout_seconds)
            except TimeoutError:
                return []
            record = self._require_access_locked(session_id, identity)
            return self._visible_events_locked(record, identity.role, after_seq)

    async def overview(self, identity: RequestIdentity) -> AdminOverviewResponse:
        if identity.role != "admin":
            raise APIError(403, "FORBIDDEN", "Credencial de gestor necessária.")
        async with self._condition:
            records = [
                record
                for record in self._records.values()
                if record.tenant_id == identity.tenant_id
            ]
            now = _utcnow()
            messages_received = sum(
                1 for record in records for message in record.messages if message.role == "customer"
            )
            recommendations_made = sum(len(record.recommendations) for record in records)
            orders_submitted = sum(
                1
                for record in records
                for event in record.events
                if event.type == EventType.ORDER_STATUS_CHANGED.value
                and event.payload.model_dump(mode="json")["status"] == "submitted"
            )
            orders_confirmed = sum(
                1
                for record in records
                for event in record.events
                if event.type == EventType.ORDER_STATUS_CHANGED.value
                and event.payload.model_dump(mode="json")["status"] == "confirmed"
            )
            recent = sorted(records, key=lambda item: item.updated_at, reverse=True)[:20]
            return AdminOverviewResponse(
                mode=Mode.REAL if any(r.mode == "real" for r in records) else Mode.DEMO,
                window=OverviewWindow(from_=now - timedelta(days=1), to=now),
                metrics=OverviewMetrics(
                    sessions_started=len(records),
                    messages_received=messages_received,
                    recommendations_made=recommendations_made,
                    orders_submitted=orders_submitted,
                    orders_confirmed=orders_confirmed,
                    conversion_rate=None,
                    average_response_ms=None,
                    estimated_ai_cost_cents=None,
                    revenue_cents=None,
                    estimated_profit_cents=None,
                ),
                recent_sessions=[
                    RecentSession(
                        session_id=record.session_id,
                        client_alias=record.client_alias,
                        status=record.status,
                        updated_at=record.updated_at,
                        last_seq=len(record.events),
                    )
                    for record in recent
                ],
            )

    async def session_client_id(self, session_id: str, identity: RequestIdentity) -> str:
        async with self._condition:
            return self._require_access_locked(session_id, identity).client_id

    async def set_session_status(
        self,
        session_id: str,
        identity: RequestIdentity,
        status: SessionStatus | str,
    ) -> None:
        resolved = SessionStatus(status).value
        async with self._condition:
            record = self._require_access_locked(session_id, identity)
            record.status = resolved
            record.updated_at = _utcnow()
            self._condition.notify_all()

    def _require_access_locked(self, session_id: str, identity: RequestIdentity) -> _SessionRecord:
        record = self._records.get(session_id)
        if record is None:
            raise APIError(404, "SESSION_NOT_FOUND", "Sessão não encontrada.")
        if record.tenant_id != identity.tenant_id:
            raise APIError(404, "SESSION_NOT_FOUND", "Sessão não encontrada.")
        if identity.role == "customer" and record.client_id != identity.subject_id:
            raise APIError(403, "FORBIDDEN", "Sessão não autorizada.")
        return record

    def _append_event_locked(
        self,
        record: _SessionRecord,
        *,
        event_type: EventType,
        actor: Actor,
        recipient: Actor | None,
        visibility: Visibility,
        payload: dict[str, Any],
    ) -> OfficeEvent:
        event = OfficeEvent(
            event_id=f"evt_{uuid4().hex}",
            seq=len(record.events) + 1,
            occurred_at=_utcnow(),
            tenant_id=record.tenant_id,
            session_id=record.session_id,
            type=event_type,
            actor=actor,
            recipient=recipient,
            visibility=visibility,
            mode=record.mode,
            payload=payload,
        )
        record.events.append(event)
        record.updated_at = event.occurred_at
        self._project_event(record, event)
        return event

    @staticmethod
    def _project_event(record: _SessionRecord, event: OfficeEvent) -> None:
        payload = event.payload.model_dump(mode="json")
        if event.type == EventType.CHAT_MESSAGE.value:
            record.messages.append(ChatMessage.model_validate(payload["message"]))
        elif event.type == EventType.AGENT_STATUS.value:
            runtime = AgentRuntime.model_validate(payload)
            record.agents[runtime.agent_id] = runtime
        elif event.type == EventType.RECOMMENDATIONS_READY.value:
            record.recommendations = [
                Recommendation.model_validate(item) for item in payload["recommendations"]
            ]
        elif event.type == EventType.CART_CHANGED.value:
            record.cart = Cart.model_validate(payload["cart"])
        elif event.type == EventType.SESSION_CLOSED.value:
            record.status = SessionStatus.CLOSED.value
        elif event.type == EventType.ERROR.value:
            record.status = SessionStatus.ERROR.value

    @staticmethod
    def _visible_events_locked(
        record: _SessionRecord, audience: Audience, after_seq: int
    ) -> list[OfficeEvent]:
        if audience == "admin":
            allowed = {Visibility.ADMIN.value, Visibility.BOTH.value}
        else:
            allowed = {Visibility.CUSTOMER.value, Visibility.BOTH.value}
        return [
            event
            for event in record.events
            if event.seq > after_seq and event.visibility in allowed
        ]


def _utcnow() -> datetime:
    return datetime.now(UTC)
