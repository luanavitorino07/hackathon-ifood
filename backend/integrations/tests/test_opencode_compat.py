from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from backend.integrations.agent_runtime import (
    _completed_tool_part,
    _map_offers,
    _raise_mcp_error,
    _tool_payload,
    _validate_tool_input,
)
from backend.integrations.config import OpenCodeSettings, SandboxLocation
from backend.integrations.errors import InvalidOutputError, QuotaError, UnavailableError
from backend.integrations.opencode_client import OpenCodeClient


@pytest.mark.parametrize(
    "status,expected",
    [
        ("connected", ["bash", "ifood_searchOffers"]),
        ("disabled", ["bash"]),
        ("failed", ["bash"]),
    ],
)
def test_builtin_only_catalog_uses_verified_configured_tool_when_connected(status, expected):
    def handler(request):
        if request.url.path == "/experimental/tool/ids":
            return httpx.Response(200, json=["bash"])
        assert request.url.path == "/mcp"
        return httpx.Response(200, json={"ifood": {"status": status}})

    async def scenario():
        async with httpx.AsyncClient(
            base_url="http://oc.test", transport=httpx.MockTransport(handler)
        ) as http:
            client = OpenCodeClient(OpenCodeSettings(), client=http)
            assert await client.list_tool_ids() == expected

    asyncio.run(scenario())


def test_actual_sanitized_mcp_fixture_preserves_promotion_and_unknown_fees():
    payload = json.loads(
        (Path(__file__).parent / "fixtures/ifood_search_real_sanitized.json").read_text(
            encoding="utf-8"
        )
    )
    offers = _map_offers(payload)
    assert offers[0]["unit_price_cents"] == 6850
    assert offers[0]["eta_minutes"] == 48
    assert offers[1]["unit_price_cents"] == 4499
    assert offers[1]["delivery_fee_cents"] == 0
    assert offers[1]["eta_minutes"] == 38
    assert all(offer["other_fees_cents"] is None and offer["tags"] == [] for offer in offers)


def test_intermediate_tool_results_are_joined_only_for_current_user_message():
    requests = []
    part = {
        "type": "tool",
        "id": "part_1",
        "tool": "ifood_searchOffers",
        "callID": "call_1",
        "state": {"status": "completed", "output": "{}"},
    }

    def handler(request):
        requests.append(request)
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "session_1"})
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "info": {"id": "final", "parentID": "user_1"},
                    "parts": [{"type": "text", "text": "OK"}],
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "info": {"role": "assistant", "parentID": "other_user"},
                    "parts": [{**part, "id": "old", "callID": "old"}],
                },
                {"info": {"role": "assistant", "parentID": "user_1"}, "parts": [part]},
                {"info": {"role": "assistant", "parentID": "user_1"}, "parts": [part]},
            ],
        )

    async def scenario():
        async with httpx.AsyncClient(
            base_url="http://oc.test", transport=httpx.MockTransport(handler)
        ) as http:
            client = OpenCodeClient(OpenCodeSettings(), client=http)
            sid = await client.create_session(title="test")
            result = await client.run_prompt(
                sid, prompt="pizza", tools={"*": False, "ifood_searchOffers": True}
            )
            assert [p["callID"] for p in result.raw_response["parts"] if p["type"] == "tool"] == [
                "call_1"
            ]

    asyncio.run(scenario())
    assert json.loads(requests[0].content)["permission"] == [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "ifood_searchOffers", "pattern": "*", "action": "allow"},
    ]
    assert json.loads(requests[1].content)["variant"] == "low"


@pytest.mark.parametrize("status,exception", [(429, QuotaError), (404, UnavailableError)])
def test_model_errors_inside_http_200_are_not_promoted_to_tool_results(status, exception):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "info": {
                    "id": "msg",
                    "error": {
                        "name": "APIError",
                        "data": {"statusCode": status, "message": "private error"},
                    },
                },
                "parts": [],
            },
        )

    async def scenario():
        async with httpx.AsyncClient(
            base_url="http://oc.test", transport=httpx.MockTransport(handler)
        ) as http:
            with pytest.raises(exception, match="^(?!.*private)"):
                await OpenCodeClient(OpenCodeSettings(), client=http).run_prompt(
                    "sid", prompt="pizza"
                )

    asyncio.run(scenario())


def test_only_current_item_restrictions_are_accepted():
    location = {"latitude": -23.55, "longitude": -46.63}
    state = {
        "input": {
            "query": "pizza",
            "resultKind": "ITEM",
            "userLocation": location,
            "refinements": {"itemRestrictions": ["VEGETARIAN"]},
        }
    }
    _validate_tool_input({"state": state}, location=location, dietary=["VEGETARIAN"])
    state["input"]["refinements"] = {"dietary": ["VEGETARIAN"]}
    with pytest.raises(InvalidOutputError):
        _validate_tool_input({"state": state}, location=location, dietary=["VEGETARIAN"])


def test_successful_search_does_not_hide_an_extra_unauthorized_tool():
    parts = [
        {"type": "tool", "tool": "ifood_searchOffers", "state": {"status": "completed"}},
        {"type": "tool", "tool": "ifood_setVoucher", "state": {"status": "completed"}},
    ]
    with pytest.raises(InvalidOutputError):
        _completed_tool_part({"parts": parts}, tool_id="ifood_searchOffers", max_tool_calls=3)


def test_mcp_error_flag_is_never_accepted_as_success():
    with pytest.raises(UnavailableError, match="mcp_error"):
        _tool_payload(
            {
                "state": {
                    "output": json.dumps(
                        {
                            "isError": True,
                            "structuredContent": {"resultKind": "ITEM", "results": []},
                        }
                    )
                }
            }
        )
    with pytest.raises(UnavailableError, match="mcp_error"):
        _raise_mcp_error({"errors": ["service failure"]})


def test_public_test_coordinates_are_not_described_as_verified_sandbox(monkeypatch):
    monkeypatch.setenv("IFOOD_SANDBOX_LATITUDE", "-23.5505")
    monkeypatch.setenv("IFOOD_SANDBOX_LONGITUDE", "-46.6333")
    monkeypatch.setenv("IFOOD_FALLBACK_LOCATION_SOURCE", "public_test")
    location = SandboxLocation.from_env()
    assert location.source == "public_test"


def test_model_cannot_add_unrequested_dietary_restriction():
    location = {"latitude": -22.0175, "longitude": -47.89083333}
    part = {
        "state": {
            "input": {
                "query": "parmegiana de frango",
                "resultKind": "ITEM",
                "userLocation": location,
                "refinements": {"itemRestrictions": ["VEGETARIAN"]},
            }
        }
    }
    with pytest.raises(InvalidOutputError):
        _validate_tool_input(part, location=location, dietary=[])


@pytest.mark.parametrize("value", [None, False, "true", 1])
def test_open_filter_must_be_boolean_true(value):
    location = {"latitude": -22.0175, "longitude": -47.89083333}
    refinements = {} if value is None else {"onlyOpen": value}
    part = {
        "state": {
            "input": {
                "query": "pizza",
                "resultKind": "ITEM",
                "userLocation": location,
                "refinements": refinements,
            }
        }
    }
    with pytest.raises(InvalidOutputError):
        _validate_tool_input(part, location=location, dietary=[], only_open=True)
    part["state"]["input"]["refinements"] = {"onlyOpen": True}
    _validate_tool_input(part, location=location, dietary=[], only_open=True)


def test_closed_merchants_are_removed_even_if_search_returned_them():
    def item(product, is_open):
        return {
            "itemId": product,
            "itemName": "Pizza",
            "unitPrice": 20,
            "merchant": {
                "merchantId": product,
                "merchantName": "MOCK",
                "isOpen": is_open,
                "deliveryMethod": {"fee": 0},
            },
        }

    result = _map_offers(
        {
            "resultKind": "ITEM",
            "results": [
                item("closed", False),
                item("open", True),
                item("unknown", None),
            ],
        }
    )
    assert [o["product_id"] for o in result] == ["open", "unknown"]
    assert result[0]["is_open"] is True
    assert "is_open" not in result[1]
    assert _map_offers({"resultKind": "ITEM", "results": [item("closed", False)]}) == []


def test_missing_oauth_is_reported_as_auth_required():
    def handler(request):
        if request.url.path == "/experimental/tool/ids":
            return httpx.Response(200, json=["bash"])
        return httpx.Response(200, json={"ifood": {"status": "needs_auth"}})

    async def scenario():
        async with httpx.AsyncClient(
            base_url="http://oc.test", transport=httpx.MockTransport(handler)
        ) as http:
            with pytest.raises(UnavailableError, match="auth_required"):
                await OpenCodeClient(OpenCodeSettings(), client=http).list_tool_ids()

    asyncio.run(scenario())
