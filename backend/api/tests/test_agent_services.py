from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

from backend.api.models import ChatMessageRequest
from backend.api.services import (
    MessageDispatch,
    OrchestratorAgentCatalog,
    OrchestratorDispatcher,
    RequestIdentity,
    StateEventSink,
)
from backend.api.state import InMemoryBackendState


def _message(session_id: str) -> MessageDispatch:
    return MessageDispatch(
        tenant_id="tenant_demo",
        client_id="client_demo_1",
        request=ChatMessageRequest(
            session_id=session_id,
            client_message_id="msg_1",
            text="Quero uma pizza",
            input_mode="text",
            transcription_id=None,
        ),
    )


def test_dispatcher_persists_agent_event_and_updates_session_status() -> None:
    async def scenario() -> None:
        state = InMemoryBackendState()
        customer = RequestIdentity("tenant_demo", "client_demo_1", "customer")
        admin = RequestIdentity("tenant_demo", "admin_demo", "admin")
        session = await state.create_session(
            identity=customer,
            client_id="client_demo_1",
        )
        sink = StateEventSink(state)

        class _Orchestrator:
            def handle_message(self, context):
                assert context == "context"
                sink.emit(
                    session_id=session.session_id,
                    type="agent_status",
                    actor={"kind": "agent", "id": "researcher"},
                    recipient=None,
                    visibility="admin",
                    payload={
                        "agent_id": "researcher",
                        "status": "done",
                        "task_id": "task_1",
                        "summary": "Busca concluída.",
                    },
                )
                return SimpleNamespace(session_status="waiting_customer")

        dispatcher = OrchestratorDispatcher(
            _Orchestrator(),
            lambda _: "context",
            sink,
        )
        await dispatcher.dispatch(_message(session.session_id))

        history = await state.history(
            session.session_id,
            admin,
            after_seq=0,
            limit=200,
        )
        snapshot = await state.snapshot(session.session_id, customer)
        assert history.events[-1].type == "agent_status"
        assert history.events[-1].event_id.startswith("evt_")
        assert history.events[-1].tenant_id == "tenant_demo"
        assert snapshot.session.status == "waiting_customer"

    asyncio.run(scenario())


def test_dispatcher_serializes_messages_from_the_same_session() -> None:
    async def scenario() -> None:
        class _Orchestrator:
            def __init__(self) -> None:
                self.active = 0
                self.maximum = 0
                self.guard = threading.Lock()

            def handle_message(self, _context):
                with self.guard:
                    self.active += 1
                    self.maximum = max(self.maximum, self.active)
                time.sleep(0.02)
                with self.guard:
                    self.active -= 1

        orchestrator = _Orchestrator()
        dispatcher = OrchestratorDispatcher(orchestrator, lambda _: object())
        message = _message("sess_1")

        await asyncio.gather(
            dispatcher.dispatch(message),
            dispatcher.dispatch(message),
        )

        assert orchestrator.maximum == 1

    asyncio.run(scenario())


def test_orchestrator_catalog_is_adapted_to_public_model() -> None:
    class _Orchestrator:
        def catalog(self):
            return [
                {
                    "agent_id": "researcher",
                    "name": "Pesquisador",
                    "role": "Busca de ofertas",
                    "description": "Pesquisa produtos e restaurantes",
                    "capabilities": ["offer_search"],
                    "enabled": True,
                }
            ]

    catalog = OrchestratorAgentCatalog(_Orchestrator())

    agents = asyncio.run(catalog.list_agents())

    assert len(agents) == 1
    assert agents[0].agent_id == "researcher"
    assert agents[0].capabilities == ["offer_search"]
