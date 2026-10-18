"""Regressões offline: reenvio HTTP não é uma nova rodada do atendimento."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.agents.testing.fakes import FakeRuntime
from backend.api.main import build_application
from backend.api.session_memory import EphemeralSessionMemory
from backend.memory import SQLiteMemory


@pytest.fixture(params=["ephemeral", "sqlite"])
def memory(request):
    instance = SQLiteMemory(":memory:") if request.param == "sqlite" else EphemeralSessionMemory()
    yield instance
    if isinstance(instance, SQLiteMemory):
        instance.close()


def message(session_id, message_id="same_message", text="Quero comida para 2 pessoas até R$ 100"):
    return dict(
        session_id=session_id,
        client_message_id=message_id,
        text=text,
        input_mode="text",
        transcription_id=None,
    )


@pytest.mark.parametrize("concurrent", [False, True])
def test_duplicate_http_message_runs_agents_once(memory, concurrent):
    runtime = FakeRuntime()
    app = build_application(runtime=runtime, memory=memory)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            payload = message(sid)
            if concurrent:
                responses = await asyncio.gather(
                    *[c.post("/api/v1/chat/messages", json=payload) for _ in range(5)]
                )
            else:
                responses = [await c.post("/api/v1/chat/messages", json=payload) for _ in range(2)]
            assert all(r.status_code == 202 for r in responses)
            assert all(r.json() == responses[0].json() for r in responses)
            assert len(runtime.calls) == 1
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert len([m for m in snapshot["messages"] if m["role"] == "customer"]) == 1
            assert len([m for m in snapshot["messages"] if m["role"] == "assistant"]) == 1
            changed = await c.post("/api/v1/chat/messages", json=message(sid, text="Quero sushi"))
            assert changed.status_code == 409
            assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
            assert len(runtime.calls) == 1
            other = (await c.post("/api/v1/sessions", json={"client_id": None})).json()[
                "session_id"
            ]
            assert (await c.post("/api/v1/chat/messages", json=message(other))).status_code == 202
            assert len(runtime.calls) == 2  # Mesmo ID em outro atendimento é independente.

    asyncio.run(scenario())


def test_failed_execution_is_not_repeated_by_http_replay(memory):
    runtime = FakeRuntime(error="quota")
    app = build_application(runtime=runtime, memory=memory)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            for _ in range(2):
                assert (await c.post("/api/v1/chat/messages", json=message(sid))).status_code == 202
            assert len(runtime.calls) == 1
            retry = await c.post(
                "/api/v1/chat/messages", json=message(sid, message_id="explicit_retry")
            )
            assert retry.status_code == 202
            assert len(runtime.calls) == 2

    asyncio.run(scenario())


def test_related_followup_should_reuse_existing_candidates(memory):
    runtime = FakeRuntime()
    app = build_application(runtime=runtime, memory=memory)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            assert (await c.post("/api/v1/chat/messages", json=message(sid))).status_code == 202
            assert len(memory.load(sid).state["candidates"]) == 3
            assert (
                await c.post(
                    "/api/v1/chat/messages",
                    json=message(sid, message_id="followup", text="Agora são 3 pessoas"),
                )
            ).status_code == 202
            assert len(runtime.calls) == 1

    asyncio.run(scenario())


def test_budget_then_quantity_followup_reuses_one_search(memory):
    runtime = FakeRuntime()
    app = build_application(runtime=runtime, memory=memory)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            sid = (await client.post("/api/v1/sessions", json={"client_id": None})).json()[
                "session_id"
            ]
            steps = [
                ("first", "Quero comida para 2 pessoas até R$ 100", 2, 10000),
                ("budget", "Até R$ 80", 2, 8000),
                ("quantity", "Agora são 3 pessoas até R$ 120", 3, 12000),
            ]
            for message_id, text, quantity, budget in steps:
                accepted = await client.post(
                    "/api/v1/chat/messages", json=message(sid, message_id, text)
                )
                assert accepted.status_code == 202
                assert len(runtime.calls) == 1
                snapshot = (await client.get(f"/api/v1/sessions/{sid}/snapshot")).json()
                assert snapshot["recommendations"]
                for rec in snapshot["recommendations"]:
                    assert sum(i["quantity"] for i in rec["items"]) == quantity
                    assert rec["total_cents"] <= budget

    asyncio.run(scenario())
