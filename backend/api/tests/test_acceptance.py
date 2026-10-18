"""Aceite HTTP/SSE contra os agentes da branch integrada, sem chamadas externas."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from backend.api.models import InitialContext, SessionCreateRequest


def context():
    return dict(name=None, age=None, location=None, preferences=[], restrictions=[])


@pytest.mark.parametrize("age", [-1, 131, True, "20", 20.5])
def test_context_rejects_invalid_age(age):
    payload = context()
    payload["age"] = age
    with pytest.raises(ValueError):
        InitialContext.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", " "),
        ("location", ""),
        ("preferences", [""]),
        ("restrictions", None),
        ("extra", "value"),
    ],
)
def test_context_rejects_invalid_fields(field, value):
    payload = context()
    payload[field] = value
    with pytest.raises(ValueError):
        InitialContext.model_validate(payload)


def test_context_optional_but_object_requires_all_five_keys():
    assert SessionCreateRequest(client_id=None).initial_context is None
    assert SessionCreateRequest(client_id=None, initial_context=None).initial_context is None
    for field in context():
        payload = context()
        del payload[field]
        with pytest.raises(ValueError):
            InitialContext.model_validate(payload)


@pytest.fixture
def main():
    pytest.importorskip("backend.agents.demo.runtime")
    from backend.api import main

    return main


def message(session_id, text, message_id="msg_1"):
    return dict(
        session_id=session_id,
        client_message_id=message_id,
        text=text,
        input_mode="text",
        transcription_id=None,
    )


def test_demo_http_acceptance_and_shared_context(main, monkeypatch):
    monkeypatch.setenv("APP_RUNTIME_MODE", "demo")
    # Demo must not even parse OpenCode/sandbox configuration.
    monkeypatch.setenv("OPENCODE_BASE_URL", "invalid")
    monkeypatch.setenv("IFOOD_SANDBOX_LATITUDE", "invalid")
    app = main.build_application()
    assert app.state.memory is app.state.agent_services.memory

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            created = await c.post(
                "/api/v1/sessions",
                json={
                    "client_id": None,
                    "initial_context": context(),
                },
            )
            assert created.status_code == 201
            assert created.json()["mode"] == "demo"
            sid = created.json()["session_id"]
            saved = app.state.memory.load(sid)
            assert saved.revision == 1
            assert saved.state["initial_context"] == context()
            response = await c.post(
                "/api/v1/chat/messages",
                json=message(
                    sid, "quero comida pra 4 pessoas até R$ 120, com uma opção vegetariana"
                ),
            )
            assert response.status_code == 202
            history = (await c.get(f"/api/v1/sessions/{sid}/history?limit=200")).json()
            assert all(e["visibility"] != "admin" for e in history["events"])
            replies = [
                e["payload"]["message"]["text"]
                for e in history["events"]
                if e["type"] == "chat_message" and e["payload"]["message"]["role"] == "assistant"
            ]
            assert any(
                "1x Escondidinho de Mandioca e Legumes" in r
                and "3x PF de Frango Grelhado" in r
                and "115,60" in r
                for r in replies
            )
            assert (await c.get("/api/v1/agents")).status_code == 403
            admin = {"X-Demo-Role": "admin"}
            catalog = await c.get("/api/v1/agents", headers=admin)
            assert catalog.status_code == 200
            assert len(catalog.json()["agents"]) == 8
            history = (
                await c.get(f"/api/v1/sessions/{sid}/history?limit=200", headers=admin)
            ).json()
            assert {
                "agent_message",
                "tool_activity",
                "pattern_identified",
                "discount_proposed",
                "decision_made",
            } <= {e["type"] for e in history["events"]}
            customer_snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            admin_snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot", headers=admin)).json()
            assert customer_snapshot["agents"] == []
            assert admin_snapshot["agents"]
            assert all(r["data_origin"] == "demo" for r in customer_snapshot["recommendations"])

            initial = context()
            initial["preferences"] = ["pizza"]
            created = await c.post(
                "/api/v1/sessions", json={"client_id": None, "initial_context": initial}
            )
            sid = created.json()["session_id"]
            await c.post(
                "/api/v1/chat/messages", json=message(sid, "quero pizza para 2 pessoas até R$ 200")
            )
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert any(
                "Combina com sua preferência: pizza" in m["text"] for m in snapshot["messages"]
            ), " | ".join(m["text"] for m in snapshot["messages"])

    asyncio.run(scenario())


def test_exact_food_preference_acceptance_with_integrated_agents(main):
    app = main.build_application(runtime_mode="demo")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            initial = context()
            initial["preferences"] = ["pizza"]
            created = await c.post(
                "/api/v1/sessions", json={"client_id": None, "initial_context": initial}
            )
            sid = created.json()["session_id"]
            await c.post(
                "/api/v1/chat/messages", json=message(sid, "quero comida para 2 pessoas até R$ 200")
            )
            assert app.state.memory.load(sid).state["constraints"]["preferences"] == ["pizza"]
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert any(
                "Combina com sua preferência: pizza" in m["text"] for m in snapshot["messages"]
            )

    asyncio.run(scenario())


def test_context_is_reloaded_for_each_message_and_mode_forwarded(main):
    from backend.agents.testing.fakes import InMemoryMemory

    memory = InMemoryMemory()
    app = main.build_application(memory=memory, runtime_mode="real")
    received = []

    class Capture:
        async def dispatch(self, message):
            received.append(message)

    app.state.message_dispatcher = Capture()
    assert app.state.agent_services.memory is memory

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            initial = context()
            initial["preferences"] = ["pizza"]
            sid = (
                await c.post(
                    "/api/v1/sessions",
                    json={
                        "client_id": None,
                        "initial_context": initial,
                    },
                )
            ).json()["session_id"]
            await c.post("/api/v1/chat/messages", json=message(sid, "oi"))
            initial["preferences"] = ["sushi"]
            memory.save_patch(sid, {"initial_context": initial}, 1, "test")
            await c.post("/api/v1/chat/messages", json=message(sid, "oi", "msg_2"))
            assert [m.initial_context["preferences"] for m in received] == [["pizza"], ["sushi"]]
            assert [m.mode for m in received] == ["real", "real"]

    asyncio.run(scenario())


def test_name_and_age_do_not_reach_runtime(main):
    from backend.agents.demo.runtime import DemoCatalogRuntime

    runtime = DemoCatalogRuntime()
    app = main.build_application(runtime=runtime, runtime_mode="demo")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            initial = context()
            initial.update(name="PessoaPrivadaTeste", age=129, location="São Paulo, SP")
            sid = (
                await c.post(
                    "/api/v1/sessions",
                    json={
                        "client_id": None,
                        "initial_context": initial,
                    },
                )
            ).json()["session_id"]
            await c.post("/api/v1/chat/messages", json=message(sid, "quero pizza até R$ 200"))
            assert runtime.calls
            for call in runtime.calls:
                assert "name" not in call.context and "age" not in call.context
                assert "PessoaPrivadaTeste" not in call.prompt + call.system

    asyncio.run(scenario())


def test_real_mode_propagates_mode_and_ignores_demo_admin(main, monkeypatch):
    from backend.agents.testing.fakes import FakeRuntime

    monkeypatch.setenv("APP_RUNTIME_MODE", "real")
    app = main.build_application(runtime=FakeRuntime())

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (
                await c.get("/api/v1/agents", headers={"X-Demo-Role": "admin"})
            ).status_code == 403
            created = await c.post("/api/v1/sessions", json={"client_id": None})
            assert created.json()["mode"] == "real"
            sid = created.json()["session_id"]
            await c.post(
                "/api/v1/chat/messages", json=message(sid, "quero pizza para 2 pessoas até R$ 200")
            )
            history = (await c.get(f"/api/v1/sessions/{sid}/history?limit=200")).json()
            assert all(e["mode"] == "real" for e in history["events"])
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert snapshot["recommendations"] == []  # fake offers cannot pass as real

    asyncio.run(scenario())


def test_runtime_selection_and_invalid_mode(main, monkeypatch):
    from backend.agents.demo.runtime import DemoCatalogRuntime

    monkeypatch.setattr(main, "OpenCodeAgentRuntime", lambda *a, **kw: DemoCatalogRuntime())
    assert main.build_application(runtime_mode="real").state.session_mode == "real"
    with pytest.raises(ValueError):
        main.build_application(runtime_mode="typo")


def test_sse_visibility_over_real_http(main):
    app = main.build_application(runtime_mode="demo")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as c:
                sid = c.post("/api/v1/sessions", json={"client_id": None}).json()["session_id"]
                c.post(
                    "/api/v1/chat/messages",
                    json=message(sid, "quero pizza para 2 pessoas até R$ 200"),
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    snapshot = c.get(f"/api/v1/sessions/{sid}/snapshot").json()
                    if any(m["role"] == "assistant" for m in snapshot["messages"]):
                        break
                    time.sleep(0.01)
                assert any(m["role"] == "assistant" for m in snapshot["messages"])
                for headers in ({}, {"X-Demo-Role": "admin"}):
                    expected = c.get(
                        f"/api/v1/sessions/{sid}/history?limit=200", headers=headers
                    ).json()["events"]
                    received = []
                    with c.stream(
                        "GET", f"/api/v1/sessions/{sid}/events", headers=headers
                    ) as stream:
                        assert stream.status_code == 200
                        for line in stream.iter_lines():
                            if line.startswith("data: "):
                                received.append(json.loads(line[6:]))
                                if len(received) == len(expected):
                                    break
                    assert received == expected
                    if not headers:
                        assert all(e["visibility"] != "admin" for e in received)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
