"""Fluxo real de código com OpenCode/MCP inteiramente simulados; sem rede."""

import asyncio
import json
import re
import unicodedata

import httpx
import pytest

from backend.api.main import build_application
from backend.integrations.agent_runtime import OpenCodeAgentRuntime
from backend.integrations.config import (
    SAO_CARLOS_TEST_COORDINATES,
    OpenCodeSettings,
    SandboxLocation,
)
from backend.integrations.opencode_client import OpenCodeClient, OpenCodeRunResult
from backend.integrations.search_quality import (
    AVAILABILITY_UNKNOWN,
    CLOSED_TEST_ONLY,
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
        self.reasoning_calls = []

    async def list_tool_ids(self):
        return ["ifood_searchOffers"]

    async def create_session(self, **kwargs):
        return "mock_session"

    async def aclose(self):
        pass

    async def run_prompt(self, session_id, **kwargs):
        if not kwargs.get("tools", {}).get("ifood_searchOffers", False):
            self.reasoning_calls.append(kwargs)
            if "Curador" in kwargs.get("system", ""):
                match = re.search(r"ITENS_JSON:\s*(.*)", kwargs["prompt"])
                items = json.loads(match.group(1)) if match else []

                def plain(value):
                    return (
                        unicodedata.normalize("NFKD", value.lower())
                        .encode("ascii", "ignore")
                        .decode()
                    )

                query = plain(self.query)
                judged = []
                for candidate in items:
                    name = plain(candidate["item"])
                    is_pizza_impostor = "pizza" in query and (
                        "pastel" in name or "esfiha" in name
                    )
                    matches = query in name and not is_pizza_impostor
                    judged.append(
                        {
                            "product_id": candidate["product_id"],
                            "fit": "sim" if matches else "nao",
                            "reason": (
                                "corresponde ao prato" if matches else "é outro tipo de prato"
                            ),
                        }
                    )
                structured = {"items": judged}
            else:
                structured = None
            return OpenCodeRunResult(
                session_id=session_id,
                message_id="mock_reasoning",
                structured_output=structured,
                raw_response={"parts": []},
            )

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
                                "refinements": {
                                    "onlyOpen": "refinements.onlyOpen=true" in kwargs["prompt"]
                                },
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
            assert "Preço, disponibilidade e personalização precisam ser confirmados" in reply
            assert "Limites da busca:" not in reply
            assert PUBLIC_LOCATION not in reply  # Detalhes continuam nas recomendações abaixo.
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


def test_http_can_show_closed_restaurant_as_unavailable_local_test_option():
    closed = item("Pizza", "closed_item", "closed_merchant", 20)
    closed["merchant"]["isOpen"] = False
    mock = MockSearchClient("pizza", [closed])
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
        include_closed_for_testing=True,
    )
    app = build_application(
        runtime=runtime,
        runtime_mode="real",
        memory_backend="ephemeral",
    )

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            session_id = (
                await client.post("/api/v1/sessions", json={"client_id": None})
            ).json()["session_id"]
            response = await client.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": session_id,
                    "client_message_id": "closed_test",
                    "text": "Quero pizza para uma pessoa até R$ 50",
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            assert response.status_code == 202
            snapshot = (await client.get(f"/api/v1/sessions/{session_id}/snapshot")).json()
            assert snapshot["recommendations"]
            assert CLOSED_TEST_ONLY in snapshot["recommendations"][0]["warnings"]
            reply = next(
                message["text"]
                for message in snapshot["messages"]
                if message["role"] == "assistant"
            )
            assert "somente para teste" in reply
            assert "não está disponível para pedido" in reply
            blocked = await client.post(
                "/api/v1/orders/submit",
                json={
                    "session_id": session_id,
                    "recommendation_id": snapshot["recommendations"][0]["recommendation_id"],
                    "client_action_id": "closed_order_attempt",
                    "confirmed": True,
                },
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "CLOSED_RESTAURANT_TEST_ONLY"

    asyncio.run(scenario())
    assert "refinements.onlyOpen=false" in mock.calls[0]["prompt"]


def test_curator_rejects_pastel_de_pizza_from_pizza_results():
    mock = MockSearchClient(
        "pizza",
        [
            item("Pizza Margherita", "pizza", "pizzaria", 35),
            item("Pastel de Pizza", "pastel", "pastelaria", 12),
        ],
    )
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
    )
    app = build_application(runtime=runtime, runtime_mode="real")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            session_id = (
                await client.post("/api/v1/sessions", json={"client_id": None})
            ).json()["session_id"]
            sent = await client.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": session_id,
                    "client_message_id": "pizza_not_pastel",
                    "text": "Quero pizza para uma pessoa até R$ 50",
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            assert sent.status_code == 202
            snapshot = (await client.get(f"/api/v1/sessions/{session_id}/snapshot")).json()
            products = {
                product["product_id"]
                for recommendation in snapshot["recommendations"]
                for product in recommendation["items"]
            }
            assert products == {"pizza"}

    asyncio.run(scenario())
    assert len(mock.calls) == 1
    assert any("Curador" in call.get("system", "") for call in mock.reasoning_calls)


def test_http_curation_uses_actual_opencode_wire_format_and_no_reasoning_history_get():
    """Exercise the HTTP adapter too: mocks of run_prompt hid the 1.19.3 regression."""
    search_items = [
        item("Pizza Grande Margherita", "pizza", "pizzaria", 35),
        item("Pastel de Pizza", "pastel", "pastelaria", 12),
        item("Esfiha sabor pizza", "esfiha", "esfiharia", 8.99),
        item("Pizza", "flavor", "esfiharia", 8.99),
    ]
    search_part = None
    reasoning_requests = []
    permissions = []

    def handler(request):
        nonlocal search_part
        if request.method == "GET":
            if request.url.path == "/experimental/tool/ids":
                return httpx.Response(200, json=["ifood_searchOffers"])
            # Only the non-structured search may request intermediate tool results.
            assert search_part is not None
            assert request.url.path == "/session/search/message"
            return httpx.Response(200, json=[{
                "info": {"role": "assistant", "parentID": "search_user"},
                "parts": [search_part],
            }])
        body = json.loads(request.content)
        if request.url.path == "/session":
            permissions.append(body["permission"])
            is_search = any(p["permission"] == "ifood_searchOffers" for p in body["permission"])
            return httpx.Response(200, json={"id": "search" if is_search else "reasoning"})
        if body["agent"] == "ifood-search":
            location = json.loads(re.search(r"userLocation=(\{.*?\})", body["parts"][0]["text"])[1])
            search_part = {
                "type": "tool", "tool": "ifood_searchOffers", "callID": "live_shape_search",
                "state": {
                    "status": "completed",
                    "input": {"query": "pizza", "resultKind": "ITEM", "userLocation": location,
                              "refinements": {"onlyOpen": True}},
                    "output": json.dumps({"resultKind": "ITEM", "results": search_items}),
                },
            }
            return httpx.Response(200, json={
                "info": {"id": "search_result", "parentID": "search_user"}, "parts": [],
            })
        assert body["agent"] == "ifood-reasoning"
        assert body["tools"] == {"*": False, "StructuredOutput": True}
        assert body["format"]["type"] == "json_schema"
        reasoning_requests.append(body)
        if "Curador" in body["system"]:
            structured = {"items": [
                {"product_id": product["itemId"],
                 "fit": "sim" if product["itemId"] == "pizza" else "nao",
                 "reason": "prato correto" if product["itemId"] == "pizza" else "outro prato"}
                for product in search_items
            ]}
        else:
            # Other agents may use their existing fallback without affecting curation.
            structured = {}
        return httpx.Response(200, json={
            "info": {"id": "reasoning_result", "parentID": "reasoning_user",
                     "structured": structured},
            "parts": [{"type": "tool", "tool": "StructuredOutput", "state": {
                "status": "completed", "input": structured, "metadata": {"valid": True},
            }}],
        })

    settings = OpenCodeSettings()
    clients = []

    def client_factory():
        client = httpx.AsyncClient(
            base_url="http://oc.test", transport=httpx.MockTransport(handler)
        )
        clients.append(client)
        return OpenCodeClient(settings, client=client)

    runtime = OpenCodeAgentRuntime(
        settings, sandbox_location=SandboxLocation(-23.55, -46.63), client_factory=client_factory,
    )
    app = build_application(runtime=runtime, runtime_mode="real", memory_backend="ephemeral")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            sid = (await client.post("/api/v1/sessions", json={"client_id": None})).json()[
                "session_id"
            ]
            sent = await client.post("/api/v1/chat/messages", json={
                "session_id": sid, "client_message_id": "wire_regression",
                "text": "Quero pizza para 2 pessoas até R$ 150",
                "input_mode": "text", "transcription_id": None,
            })
            assert sent.status_code == 202
            recs = (await client.get(f"/api/v1/sessions/{sid}/snapshot")).json()["recommendations"]
            assert recs
            assert {i["product_id"] for rec in recs for i in rec["items"]} == {"pizza"}
        for client in clients:
            await client.aclose()

    asyncio.run(scenario())
    assert reasoning_requests
    assert permissions[1] == [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "StructuredOutput", "pattern": "*", "action": "allow"},
    ]


def test_http_preserves_verified_delivery_and_catalog_details():
    detailed = item("Pizza Margherita", "pizza", "pizzaria", 39.9)
    detailed.update(
        {
            "promotionalUnitPrice": 34.9,
            "imageUrl": "https://images.example/pizza.jpg",
        }
    )
    detailed["merchant"].update(
        {
            "isOpen": True,
            "distanceKm": 2.4,
            "rating": 4.7,
            "deliveryMethod": {
                "fee": 5,
                "estimatedMinutes": {"min": 25, "max": 40},
            },
        }
    )
    mock = MockSearchClient("pizza", [detailed])
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
    )
    app = build_application(runtime=runtime, runtime_mode="real")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            session_id = (
                await client.post("/api/v1/sessions", json={"client_id": None})
            ).json()["session_id"]
            await client.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": session_id,
                    "client_message_id": "verified_details",
                    "text": "Quero pizza para uma pessoa até R$ 50",
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            recommendation = (
                await client.get(f"/api/v1/sessions/{session_id}/snapshot")
            ).json()["recommendations"][0]
            assert recommendation["eta_min_minutes"] == 25
            assert recommendation["eta_minutes"] == 40
            assert recommendation["distance_km"] == 2.4
            assert recommendation["merchant_rating"] == 4.7
            assert recommendation["is_open"] is True
            assert DISTANCE_UNKNOWN not in recommendation["warnings"]
            assert recommendation["items"][0]["unit_price_cents"] == 3490
            assert recommendation["items"][0]["original_unit_price_cents"] == 3990
            assert recommendation["items"][0]["image_url"] == (
                "https://images.example/pizza.jpg"
            )

    asyncio.run(scenario())


def test_ai_selected_query_is_not_overridden_by_legacy_product_terms():
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
            prompt="Pedido do cliente: Quero parmegiana de frango\n"
            "Produto desejado: parmegiana frango.",
            output_schema={},
            allowed_tools=("offer_search",),
        )
    )
    assert outcome.ok is True
    assert len(mock.calls) == 1
    search_prompt = mock.calls[0]["prompt"]
    assert "Pedido original do cliente:\nQuero parmegiana de frango" in search_prompt
    assert "Produto desejado" not in search_prompt
    assert "Termos obrigatórios" not in search_prompt
    assert outcome.tool_calls[0].provider == "ifood_mcp"


def test_ai_interprets_full_hamburger_request_without_literal_word_query():
    request = (
        "eu quero um hamburguer com bastante carne, molho num preco legal, "
        "perto de 40 reais, se tiver batata legal e o mais perto possivel"
    )
    mock = MockSearchClient(
        "hamburguer",
        [item("Hambúrguer duplo com batata", "burger_1", "merchant_1", 35.9)],
    )
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
    )
    app = build_application(runtime=runtime, runtime_mode="real")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            session_id = (
                await client.post("/api/v1/sessions", json={"client_id": None})
            ).json()["session_id"]
            await client.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": session_id,
                    "client_message_id": "semantic_search",
                    "text": request,
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            snapshot = (
                await client.get(f"/api/v1/sessions/{session_id}/snapshot")
            ).json()

        assert snapshot["recommendations"]
        assert len(mock.calls) == 1
        search_prompt = mock.calls[0]["prompt"]
        assert f"Pedido original do cliente:\n{request}" in search_prompt
        assert "Produto desejado" not in search_prompt
        assert "Termos obrigatórios" not in search_prompt

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text, product",
    [
        (
            "quero marmita parmegiana pra 2 pessoas por 100 conto no maximo, busque melhor preço",
            "marmita parmegiana",
        ),
        ("na verdade quero pizza", "pizza"),
        ("me vê um xis salada pfv", "xis salada"),
    ],
)
def test_claude_review_phrases_through_agents_runtime_and_http(text, product):
    mock = MockSearchClient(product, [item(product, "p1", "m1", 20)])
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
    )
    app = build_application(runtime=runtime, runtime_mode="real")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            await c.post(
                "/api/v1/chat/messages",
                json={
                    "session_id": sid,
                    "client_message_id": "regression",
                    "text": text,
                    "input_mode": "text",
                    "transcription_id": None,
                },
            )
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert snapshot["recommendations"]
            assert all(
                i["name"] == product for r in snapshot["recommendations"] for i in r["items"]
            )
            assert len(mock.calls) == 1

    asyncio.run(scenario())


def test_cheaper_after_expired_search_uses_remembered_product_not_word_algo():
    mock = MockSearchClient("pizza", [item("pizza", "p1", "m1", 20)])
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: mock,
    )
    app = build_application(runtime=runtime, runtime_mode="real")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            for index, text in enumerate(["Quero pizza até R$ 100", "tem algo mais barato?"]):
                if index:
                    stored = app.state.memory.load(sid)
                    app.state.memory.save_patch(
                        sid,
                        {"last_search": {**stored.state["last_search"], "at": 0}},
                        stored.revision,
                        "test_expiration",
                    )
                    mock.items = [item("pizza", "p1", "m1", 15)]
                await c.post(
                    "/api/v1/chat/messages",
                    json={
                        "session_id": sid,
                        "client_message_id": f"message_{index}",
                        "text": text,
                        "input_mode": "text",
                        "transcription_id": None,
                    },
                )
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert snapshot["recommendations"]
            assert snapshot["recommendations"][0]["items"][0]["unit_price_cents"] == 1500
            assert len(mock.calls) == 2
            assert "Pedido original do cliente:\ntem algo mais barato?" in mock.calls[-1]["prompt"]
            assert "Produto desejado" not in mock.calls[-1]["prompt"]

    asyncio.run(scenario())


def test_evidence_ttl_matches_agent_resumption():
    from backend.agents.resumption import SEARCH_TTL_S
    from backend.integrations.search_quality import SearchEvidenceStore

    assert SEARCH_TTL_S == SearchEvidenceStore()._ttl == 300
