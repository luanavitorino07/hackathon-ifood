from __future__ import annotations

import asyncio
from importlib import import_module

import httpx
import pytest

from backend.api.session_memory import EphemeralSessionMemory
from backend.memory import SQLiteMemory

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


def test_default_composition_uses_sqlite_memory(tmp_path, monkeypatch) -> None:
    main = import_module("backend.api.main")
    database = tmp_path / "api-memory.sqlite3"
    monkeypatch.setenv("APP_MEMORY_PATH", str(database))

    app = main.build_application(runtime=agent_fakes.FakeRuntime())

    assert isinstance(app.state.memory, SQLiteMemory)
    assert app.state.agent_services.memory is app.state.memory
    assert app.state.memory_backend == "SQLiteMemory"
    assert database.is_file()
    app.state.memory.close()


def test_ephemeral_memory_remains_an_explicit_option() -> None:
    main = import_module("backend.api.main")

    app = main.build_application(
        runtime=agent_fakes.FakeRuntime(),
        memory_backend="ephemeral",
    )

    assert isinstance(app.state.memory, EphemeralSessionMemory)
    assert app.state.agent_services.memory is app.state.memory


def test_real_local_demo_admin_uses_httponly_cookie_for_followup_requests() -> None:
    main = import_module("backend.api.main")
    app = main.build_application(
        runtime=agent_fakes.FakeRuntime(),
        runtime_mode="real",
        memory_backend="ephemeral",
        allow_local_demo_admin=True,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 4321))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
        ) as client:
            assert (await client.get("/api/v1/agents")).status_code == 403
            authorized = await client.get(
                "/api/v1/admin/overview",
                headers={"X-Demo-Role": "admin"},
            )
            assert authorized.status_code == 200
            cookie = authorized.headers["set-cookie"]
            assert "ifood_local_demo_admin=" in cookie
            assert "HttpOnly" in cookie
            assert "SameSite=strict" in cookie

            # Simula o EventSource: sem cabeçalho customizado, usando só o cookie.
            assert (await client.get("/api/v1/agents")).status_code == 200

    asyncio.run(scenario())


def test_real_local_demo_admin_rejects_non_loopback_client() -> None:
    main = import_module("backend.api.main")
    app = main.build_application(
        runtime=agent_fakes.FakeRuntime(),
        runtime_mode="real",
        memory_backend="ephemeral",
        allow_local_demo_admin=True,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 4321))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
        ) as client:
            response = await client.get(
                "/api/v1/agents",
                headers={"X-Demo-Role": "admin"},
            )
            assert response.status_code == 403
            assert "set-cookie" not in response.headers

    asyncio.run(scenario())
