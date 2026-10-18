from __future__ import annotations

import asyncio
from importlib import import_module

import httpx
import pytest

agent_fakes = pytest.importorskip("backend.agents.testing.fakes")


def test_executable_app_connects_the_orchestrator_to_http() -> None:
    main = import_module("backend.api.main")
    app = main.build_application(runtime=agent_fakes.FakeRuntime())

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            created = await client.post(
                "/api/v1/sessions",
                json={"client_id": "client_demo_1"},
            )
            session_id = created.json()["session_id"]
            accepted = await client.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": session_id,
                    "client_message_id": "msg_1",
                    "text": "Quero uma pizza até 70 reais",
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            snapshot = await client.get(f"/api/v1/sessions/{session_id}/snapshot")
            history = await client.get(
                f"/api/v1/sessions/{session_id}/history",
                params={"after_seq": 0, "limit": 200},
            )

        assert created.status_code == 201
        assert accepted.status_code == 202
        assert snapshot.status_code == 200
        assert snapshot.json()["recommendations"]
        assert all(
            event["payload"].get("code") != "RUNTIME_UNAVAILABLE"
            for event in history.json()["events"]
            if event["type"] == "error"
        )

    asyncio.run(scenario())
