from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.chat_cli import (
    APIChatClient,
    format_recommendations,
    format_runtime_stack,
    format_tool_activity,
)


def test_chat_cli_runs_complete_demo_conversation():
    main = pytest.importorskip("backend.api.main")
    app = main.build_application(runtime_mode="demo", memory_backend="ephemeral")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://chat.test"
        ) as http_client:
            chat = APIChatClient(http_client, response_timeout_s=2, poll_interval_s=0)
            session = await chat.start(preferences=("pizza",))
            reply, recommendations = await chat.send("quero pizza para 2 pessoas até R$ 200")

            assert session["mode"] == "demo"
            assert "pizza" in reply.casefold()
            assert recommendations
            rendered = format_recommendations(recommendations)
            assert "Recomendações:" in rendered
            assert "R$" in rendered
            activity = format_tool_activity(chat.tool_activity)
            assert "offer_search" in activity
            assert "raciocinio_ia" in activity
            assert "simulação local, sem rede" in activity
            assert "agente researcher" in activity
            assert "agente curator" in activity

    asyncio.run(scenario())


def test_chat_cli_keeps_followups_in_the_same_session():
    main = pytest.importorskip("backend.api.main")
    app = main.build_application(runtime_mode="demo", memory_backend="ephemeral")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://chat.test"
        ) as http_client:
            chat = APIChatClient(http_client, response_timeout_s=2, poll_interval_s=0)
            await chat.start()
            await chat.send("quero pizza para 2 pessoas até R$ 200")
            reply, _ = await chat.send("agora são 3 pessoas")
            snapshot = await chat.snapshot()

            assert len([m for m in snapshot["messages"] if m["role"] == "customer"]) == 2
            assert "3x" in reply

    asyncio.run(scenario())


def test_recommendation_formatter_shows_delivery_distance_and_rating():
    rendered = format_recommendations(
        [
            {
                "merchant_name": "Pizza Boa",
                "items": [{"quantity": 1, "name": "Pizza grande"}],
                "total_cents": 5290,
                "eta_min_minutes": 30,
                "eta_minutes": 45,
                "distance_km": 2.4,
                "merchant_rating": 4.8,
            }
        ]
    )

    assert "R$ 52,90" in rendered
    assert "entrega 30-45 min" in rendered
    assert "2.4 km" in rendered
    assert "nota 4.8" in rendered


def test_runtime_stack_makes_demo_integrations_explicit():
    rendered = format_runtime_stack(real=False)

    assert "offer_search" in rendered
    assert "raciocinio_ia" in rendered
    assert "OpenCode, Gemini e MCP iFood: NÃO utilizados" in rendered


def test_tool_activity_formatter_does_not_claim_unrecorded_tools():
    assert "nenhuma atividade" in format_tool_activity([])
