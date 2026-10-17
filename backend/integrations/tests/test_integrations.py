from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.integrations.config import (
    IFOOD_MCP_URL,
    OpenCodeSettings,
    SandboxLocation,
    build_ifood_mcp_config,
)
from backend.integrations.errors import InvalidOutputError, QuotaError
from backend.integrations.offer_search import DemoOfferSearch
from backend.integrations.opencode_client import OpenCodeClient


def test_ifood_config_references_environment_instead_of_secrets() -> None:
    config = build_ifood_mcp_config()

    assert config["url"] == IFOOD_MCP_URL
    assert config["oauth"] == {
        "clientId": "{env:IFOOD_MCP_CLIENT_ID}",
        "clientSecret": "{env:IFOOD_MCP_CLIENT_SECRET}",
        "scope": "mcp.discovery.search.read",
    }


def test_sandbox_location_validates_ranges() -> None:
    with pytest.raises(ValueError):
        SandboxLocation(latitude=91, longitude=0)


def test_demo_offer_search_never_claims_ifood_origin() -> None:
    search = DemoOfferSearch(SandboxLocation(latitude=-23.55, longitude=-46.63))

    execution = asyncio.run(
        search.execute(
            {
                "query": "pizza até 60 reais",
                "filters": {"max_item_price_cents": 6_000},
            }
        )
    )

    assert execution.tool_name == "offer_search"
    assert execution.provider == "demo"
    assert execution.output["data_origin"] == "demo"
    assert execution.output["items"][0]["unit_price_cents"] == 4_990
    assert "demonstra" in execution.output["warnings"][0].lower()


def test_opencode_client_health_and_structured_prompt() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "1.2.3"})
        if request.url.path == "/session":
            return httpx.Response(200, json={"id": "oc_session_1"})
        if request.url.path == "/session/oc_session_1/message":
            return httpx.Response(
                200,
                json={
                    "info": {
                        "id": "oc_message_1",
                        "structured_output": {"answer": "ok"},
                    },
                    "parts": [],
                },
            )
        raise AssertionError(f"request inesperada: {request.method} {request.url}")

    async def scenario() -> None:
        async_client = httpx.AsyncClient(
            base_url="http://opencode.test", transport=httpx.MockTransport(handler)
        )
        client = OpenCodeClient(OpenCodeSettings(), client=async_client)
        health = await client.health()
        session_id = await client.create_session(title="sess_1")
        result = await client.run_prompt(
            session_id,
            prompt="Retorne JSON",
            tools={"ifood_searchOffers": True},
            output_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        )
        await async_client.aclose()

        assert health.version == "1.2.3"
        assert result.structured_output == {"answer": "ok"}

    asyncio.run(scenario())

    prompt_request = requests[-1]
    body = json.loads(prompt_request.content)
    assert body["model"] == {
        "providerID": "google",
        "modelID": "gemini-2.5-flash",
    }
    assert body["tools"] == {"ifood_searchOffers": True}
    assert body["format"]["type"] == "json_schema"


def test_opencode_client_maps_429_to_quota() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    async def scenario() -> None:
        async_client = httpx.AsyncClient(
            base_url="http://opencode.test", transport=httpx.MockTransport(handler)
        )
        client = OpenCodeClient(OpenCodeSettings(), client=async_client)
        with pytest.raises(QuotaError):
            await client.health()
        await async_client.aclose()

    asyncio.run(scenario())


def test_opencode_client_rejects_invalid_health_payload() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"healthy": False})

    async def scenario() -> None:
        async_client = httpx.AsyncClient(
            base_url="http://opencode.test", transport=httpx.MockTransport(handler)
        )
        client = OpenCodeClient(OpenCodeSettings(), client=async_client)
        with pytest.raises(InvalidOutputError):
            await client.health()
        await async_client.aclose()

    asyncio.run(scenario())
