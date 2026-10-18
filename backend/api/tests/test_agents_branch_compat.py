from __future__ import annotations

import asyncio

import pytest

from backend.api.models import ChatMessageRequest
from backend.api.services import MessageDispatch, RequestIdentity, build_demo_agent_services
from backend.api.state import InMemoryBackendState

agent_fakes = pytest.importorskip("backend.agents.testing.fakes")


def test_api_composition_runs_the_published_agent_contract_end_to_end() -> None:
    async def scenario() -> None:
        state = InMemoryBackendState()
        customer = RequestIdentity("tenant_demo", "client_demo_1", "customer")
        session = await state.create_session(
            identity=customer,
            client_id="client_demo_1",
        )
        runtime = agent_fakes.FakeRuntime()
        services = build_demo_agent_services(runtime=runtime, state=state)
        request = ChatMessageRequest(
            session_id=session.session_id,
            client_message_id="msg_1",
            text="Quero uma pizza até 70 reais",
            input_mode="text",
            transcription_id=None,
        )
        await state.accept_message(request, customer)

        await services.dispatcher.dispatch(
            MessageDispatch(
                tenant_id="tenant_demo",
                client_id="client_demo_1",
                request=request,
            )
        )

        snapshot = await state.snapshot(session.session_id, customer)
        assert len(runtime.calls) == 1
        assert runtime.calls[0].allowed_tools == ("offer_search",)
        assert snapshot.session.status == "active"
        assert snapshot.recommendations
        assert snapshot.recommendations[0].data_origin == "demo"

    asyncio.run(scenario())
