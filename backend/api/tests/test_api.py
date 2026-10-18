from __future__ import annotations

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from backend.api.app import create_app
from backend.api.models import (
    Actor,
    AgentDefinition,
    ChatMessageRequest,
    EventType,
    OfficeEvent,
    SessionCreateRequest,
)
from backend.api.services import RequestIdentity
from backend.api.sse import format_office_event
from backend.api.state import InMemoryBackendState


class _StaticIdentityResolver:
    def __init__(self, role: str) -> None:
        self._role = role

    async def resolve(self, request):
        del request
        return RequestIdentity(
            tenant_id="tenant_demo",
            subject_id="admin_demo" if self._role == "admin" else "client_demo_1",
            role=self._role,
        )


class _AgentCatalog:
    async def list_agents(self):
        return [
            AgentDefinition(
                agent_id="researcher",
                name="Pesquisador",
                role="Busca de ofertas",
                description="Pesquisa produtos e restaurantes",
                capabilities=["offer_search"],
                enabled=True,
            )
        ]


def test_session_contract_rejects_incomplete_initial_context() -> None:
    with pytest.raises(ValidationError):
        SessionCreateRequest.model_validate(
            {
                "client_id": "client_demo_1",
                "initial_context": {
                    "name": "Ana",
                    "location": "São Paulo, SP",
                },
            }
        )


def test_chat_contract_links_audio_to_transcription() -> None:
    with pytest.raises(ValidationError):
        ChatMessageRequest(
            session_id="sess_1",
            client_message_id="msg_1",
            text="Olá",
            input_mode="audio",
            transcription_id=None,
        )


def test_office_event_rejects_extra_payload_keys() -> None:
    with pytest.raises(ValidationError):
        OfficeEvent(
            event_id="evt_1",
            seq=1,
            occurred_at="2026-10-17T18:00:00Z",
            tenant_id="tenant_demo",
            session_id="sess_1",
            type="session_started",
            actor={"kind": "system", "id": "api"},
            recipient=None,
            visibility="both",
            mode="demo",
            payload={"client_alias": "Cliente #1", "extra": True},
        )


def test_sse_uses_seq_as_id_and_fixed_event_name() -> None:
    event = OfficeEvent(
        event_id="evt_4",
        seq=4,
        occurred_at="2026-10-17T18:00:00Z",
        tenant_id="tenant_demo",
        session_id="sess_1",
        type="session_started",
        actor={"kind": "system", "id": "api"},
        recipient=None,
        visibility="both",
        mode="demo",
        payload={"client_alias": "Cliente #1"},
    )

    encoded = format_office_event(event)

    assert encoded.startswith("id: 4\nevent: office_event\ndata: ")
    assert encoded.endswith("\n\n")


def test_state_is_idempotent_and_filters_admin_events() -> None:
    async def scenario() -> None:
        state = InMemoryBackendState()
        customer = RequestIdentity("tenant_demo", "client_demo_1", "customer")
        admin = RequestIdentity("tenant_demo", "admin_demo", "admin")
        session = await state.create_session(identity=customer, client_id="client_demo_1")
        message = ChatMessageRequest(
            session_id=session.session_id,
            client_message_id="msg_1",
            text="Quero pizza",
            input_mode="text",
            transcription_id=None,
        )
        first = await state.accept_message(message, customer)
        second = await state.accept_message(message, customer)
        await state.publish_event(
            session_id=session.session_id,
            identity=admin,
            event_type=EventType.TOOL_ACTIVITY,
            actor=Actor(kind="tool", id="demo_catalog"),
            recipient=Actor(kind="agent", id="researcher"),
            visibility="admin",
            payload={
                "call_id": "call_1",
                "tool_name": "offer_search",
                "provider": "demo",
                "status": "succeeded",
                "duration_ms": 10,
                "summary": "Busca demo concluída.",
            },
        )

        customer_history = await state.history(session.session_id, customer, after_seq=0, limit=200)
        admin_history = await state.history(session.session_id, admin, after_seq=0, limit=200)

        assert first == second
        assert [event.type for event in customer_history.events] == [
            "session_started",
            "chat_message",
        ]
        assert admin_history.events[-1].type == "tool_activity"

    asyncio.run(scenario())


def test_http_flow_accepts_message_and_emits_honest_runtime_error() -> None:
    async def scenario() -> None:
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            session_response = await client.post(
                "/api/v1/sessions", json={"client_id": "client_demo_1"}
            )
            assert session_response.status_code == 201
            session_id = session_response.json()["session_id"]

            message_response = await client.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": session_id,
                    "client_message_id": "msg_front_1",
                    "text": "Quero uma pizza até 60 reais",
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            assert message_response.status_code == 202
            assert message_response.json()["status"] == "accepted"

            history = await client.get(
                f"/api/v1/sessions/{session_id}/history",
                params={"after_seq": 0, "limit": 200},
            )
            assert history.status_code == 200
            event_types = [event["type"] for event in history.json()["events"]]
            assert event_types == ["session_started", "chat_message", "error"]
            assert history.json()["events"][-1]["payload"]["code"] == ("RUNTIME_UNAVAILABLE")

    asyncio.run(scenario())


def test_http_errors_use_the_common_contract() -> None:
    async def scenario() -> None:
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            invalid = await client.post(
                "/api/v1/sessions",
                json={"client_id": "client_demo_1", "unknown": None},
            )
            assert invalid.status_code == 422
            assert set(invalid.json()) == {"schema_version", "request_id", "error"}
            assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

            audio = await client.post("/api/v1/audio/transcriptions")
            assert audio.status_code == 503
            assert audio.json()["error"]["code"] == "STT_UNAVAILABLE"

    asyncio.run(scenario())


def test_openapi_contains_all_public_v1_routes_and_payload_schemas() -> None:
    schema = create_app().openapi()
    expected_paths = {
        "/api/v1/sessions",
        "/api/v1/audio/transcriptions",
        "/api/v1/chat/messages",
        "/api/v1/agents",
        "/api/v1/sessions/{session_id}/snapshot",
        "/api/v1/sessions/{session_id}/history",
        "/api/v1/admin/overview",
        "/api/v1/orders/submit",
        "/api/v1/sessions/{session_id}/events",
    }

    assert expected_paths == set(schema["paths"])
    office_event = schema["components"]["schemas"]["OfficeEvent"]
    payload_schema = office_event["properties"]["payload"]
    assert "anyOf" in payload_schema
    audio_content = schema["paths"]["/api/v1/audio/transcriptions"]["post"]["requestBody"][
        "content"
    ]
    assert "multipart/form-data" in audio_content
    event_content = schema["paths"]["/api/v1/sessions/{session_id}/events"]["get"]["responses"][
        "200"
    ]["content"]
    assert "text/event-stream" in event_content


def test_admin_catalog_and_overview_require_admin_identity() -> None:
    async def scenario() -> None:
        customer_app = create_app()
        customer_transport = httpx.ASGITransport(app=customer_app)
        async with httpx.AsyncClient(
            transport=customer_transport, base_url="http://testserver"
        ) as customer:
            forbidden = await customer.get("/api/v1/admin/overview")
            assert forbidden.status_code == 403

        admin_app = create_app(
            identity_resolver=_StaticIdentityResolver("admin"),
            agent_catalog=_AgentCatalog(),
        )
        admin_transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(
            transport=admin_transport, base_url="http://testserver"
        ) as admin:
            catalog = await admin.get("/api/v1/agents")
            overview = await admin.get("/api/v1/admin/overview")
            assert catalog.status_code == 200
            assert catalog.json()["agents"][0]["capabilities"] == ["offer_search"]
            assert overview.status_code == 200
            assert set(overview.json()["window"]) == {"from", "to"}

    asyncio.run(scenario())
