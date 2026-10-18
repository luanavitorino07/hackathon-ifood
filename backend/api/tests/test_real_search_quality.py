"""Fluxo real de código com OpenCode/MCP inteiramente simulados; sem rede."""

import asyncio
import json
import re

import httpx
import pytest

from backend.api.main import build_application
from backend.integrations.agent_runtime import OpenCodeAgentRuntime
from backend.integrations.config import (
    SAO_CARLOS_TEST_COORDINATES,
    OpenCodeSettings,
    SandboxLocation,
)
from backend.integrations.opencode_client import OpenCodeRunResult
from backend.integrations.search_quality import (
    AVAILABILITY_UNKNOWN,
    CUSTOMIZATION_UNKNOWN,
    DISTANCE_UNKNOWN,
    OPEN_FILTERED,
    PUBLIC_LOCATION,
)


def item(name, product, merchant, price):
    return {
        "itemId": product,
        "itemName": name,
        "unitPrice": price,
        "merchant": {
            "merchantId": merchant,
            "merchantName": merchant + " MOCK",
            "deliveryMethod": {"fee": 2, "estimatedMinutes": {"max": 30}},
        },
    }


class MockSearchClient:
    def __init__(self, query, items):
        self.query, self.items, self.calls = query, items, []

    async def list_tool_ids(self):
        return ["ifood_searchOffers"]

    async def create_session(self, **kwargs):
        return "mock_session"

    async def aclose(self):
        pass

    async def run_prompt(self, session_id, **kwargs):
        self.calls.append(kwargs)
        location = json.loads(re.search(r"userLocation=(\{.*?\})", kwargs["prompt"])[1])
        return OpenCodeRunResult(
            session_id=session_id,
            message_id="mock_message",
            structured_output=None,
            raw_response={
                "parts": [
                    {
                        "type": "tool",
                        "tool": "ifood_searchOffers",
                        "callID": "mock_call",
                        "state": {
                            "status": "completed",
                            "input": {
                                "query": self.query,
                                "resultKind": "ITEM",
                                "userLocation": location,
                                "refinements": {"onlyOpen": True},
                            },
                            "output": json.dumps({"resultKind": "ITEM", "results": self.items}),
                        },
                    }
                ]
            },
        )


@pytest.mark.parametrize("customization", [False, True])
def test_http_returns_only_requested_dish_prices_and_honest_catalog_warnings(customization):
    query = "hamburguer" if customization else "parmegiana de frango"
    dish = "Hambúrguer artesanal" if customization else "Parmegiana de frango"
    mock = MockSearchClient(
        query,
        [
            item("Strogonoff de frango", "wrong", "m1", 10),
            item(dish, "a", "m1", 25.9),
            item(dish, "b", "m2", 29.9),
        ],
    )
    mock.items.append(
        {
            **item(dish, "closed", "closed_merchant", 1),
            "merchant": {
                "merchantId": "closed_merchant",
                "merchantName": "CLOSED MOCK",
                "isOpen": False,
                "deliveryMethod": {"fee": 0},
            },
        }
    )
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(*SAO_CARLOS_TEST_COORDINATES, source="public_test"),
        client_factory=lambda: mock,
    )
    app = build_application(runtime=runtime, runtime_mode="real")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            text = "Quero hamburguer sem cebola" if customization else "Quero parmegiana de frango"
            sent = await c.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": sid,
                    "client_message_id": "quality_message",
                    "text": text + " para 2 pessoas até R$ 200",
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            assert sent.status_code == 202
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            recs = snapshot["recommendations"]
            assert {r["merchant_id"] for r in recs} == {"m1", "m2"}
            reply = next(m["text"] for m in snapshot["messages"] if m["role"] == "assistant")
            assert CUSTOMIZATION_UNKNOWN in reply
            assert PUBLIC_LOCATION in reply
            for rec in recs:
                assert all(i["product_id"] != "wrong" for i in rec["items"])
                assert all(i["unit_price_cents"] in (2590, 2990) for i in rec["items"])
                assert OPEN_FILTERED in rec["warnings"]
                assert AVAILABILITY_UNKNOWN not in rec["warnings"]
                assert DISTANCE_UNKNOWN in rec["warnings"]
                assert CUSTOMIZATION_UNKNOWN in rec["warnings"]
                assert PUBLIC_LOCATION in rec["warnings"]
                if customization:
                    assert any("personalização solicitada" in w for w in rec["warnings"])
            history = (await c.get(f"/api/v1/sessions/{sid}/history")).json()
            assert all(e["visibility"] != "admin" for e in history["events"])
            ready = [e for e in history["events"] if e["type"] == "recommendations_ready"]
            assert ready[-1]["payload"]["recommendations"] == recs
            if customization:
                second = (await c.post("/api/v1/sessions", json={"client_id": None})).json()[
                    "session_id"
                ]
                await c.post(
                    "/api/v1/chat/messages",
                    json={
                        "session_id": second,
                        "client_message_id": "other_session",
                        "text": "Quero hamburguer para 2 pessoas até R$ 200",
                        "input_mode": "text",
                        "transcription_id": None,
                    },
                )
                other = (await c.get(f"/api/v1/sessions/{second}/snapshot")).json()
                other_reply = next(m["text"] for m in other["messages"] if m["role"] == "assistant")
                assert "personalização solicitada" not in other_reply

    asyncio.run(scenario())
    assert len(mock.calls) == (2 if customization else 1)
    assert all("refinements.onlyOpen=true" in call["prompt"] for call in mock.calls)
    assert all("pageSize=20" in call["prompt"] for call in mock.calls)


def test_query_substitution_is_rejected_without_automatic_retry():
    mock = MockSearchClient("strogonoff de frango", [item("Strogonoff de frango", "x", "m", 20)])
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
    )
    from backend.agents.ports import RuntimeCall

    outcome = runtime.run(
        RuntimeCall(
            agent_id="researcher",
            task_id="t",
            session_id="s",
            system="",
            prompt="Pedido do cliente: Quero parmegiana de frango",
            output_schema={},
            allowed_tools=("offer_search",),
        )
    )
    assert outcome.ok is False
    assert outcome.detail == "invalid_query"
    assert len(mock.calls) == 1
    assert outcome.tool_calls == ()
