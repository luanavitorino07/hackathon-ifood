from __future__ import annotations

import asyncio
import json
from importlib import import_module
from types import SimpleNamespace

import pytest

from backend.integrations.agent_runtime import OpenCodeAgentRuntime
from backend.integrations.config import OpenCodeSettings, SandboxLocation
from backend.integrations.opencode_client import OpenCodeRunResult


class _FakeOpenCode:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.closed = False
        self.prompt_kwargs = None

    async def list_tool_ids(self) -> list[str]:
        return ["bash", "ifood_searchOffers"]

    async def create_session(self, *, title: str | None = None) -> str:
        assert title == "researcher:task_1"
        return "oc_session_1"

    async def run_prompt(self, session_id: str, **kwargs) -> OpenCodeRunResult:
        assert session_id == "oc_session_1"
        self.prompt_kwargs = kwargs
        return OpenCodeRunResult(
            session_id=session_id,
            message_id="msg_1",
            structured_output={"offers": [{"invented": True}]},
            raw_response={
                "info": {"id": "msg_1"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "ifood_searchOffers",
                        "callID": "call_real_1",
                        "state": {
                            "status": "completed",
                            "input": {
                                "query": "pizza",
                                "resultKind": "ITEM",
                                "userLocation": {
                                    "latitude": -23.55,
                                    "longitude": -46.63,
                                },
                                "refinements": {"dietary": ["VEGETARIAN"]},
                            },
                            "output": json.dumps(self.payload),
                            "time": {"start": 1000, "end": 1042},
                        },
                    }
                ],
            },
        )

    async def aclose(self) -> None:
        self.closed = True


def _call(**context):
    return SimpleNamespace(
        agent_id="researcher",
        task_id="task_1",
        session_id="sess_1",
        system="Use somente ferramentas autorizadas.",
        prompt="Pedido do cliente: pizza até 60 reais",
        allowed_tools=("offer_search",),
        max_tool_calls=3,
        timeout_s=60.0,
        context=context,
    )


def test_runtime_maps_raw_mcp_output_and_ignores_model_structured_output() -> None:
    payload = {
        "resultKind": "ITEM",
        "results": [
            {
                "itemId": "item_1",
                "itemName": "Pizza Margherita",
                "unitPrice": 32.9,
                "promotionalUnitPrice": 29.0,
                "merchant": {
                    "merchantId": "merchant_1",
                    "merchantName": "Pizza Express",
                    "deliveryMethod": {
                        "fee": 6.5,
                        "promotionalFee": 0,
                        "estimatedMinutes": {"min": 30, "max": 45},
                    },
                },
            }
        ],
    }
    client = _FakeOpenCode(payload)
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: client,
    )

    result = asyncio.run(runtime._execute(_call(dietary_filters=["VEGETARIAN"])))

    assert result.ok is True
    assert result.structured == {
        "offers": [
            {
                "product_id": "item_1",
                "name": "Pizza Margherita",
                "unit_price_cents": 2900,
                "merchant_id": "merchant_1",
                "merchant_name": "Pizza Express",
                "tags": [],
                "delivery_fee_cents": 0,
                "other_fees_cents": None,
                "eta_minutes": 45,
            }
        ]
    }
    assert result.traces[0].provider == "ifood_mcp"
    assert result.traces[0].status == "succeeded"
    assert client.prompt_kwargs["tools"] == {
        "bash": False,
        "ifood_searchOffers": True,
    }
    assert '"latitude": -23.55' in client.prompt_kwargs["prompt"]
    assert client.prompt_kwargs["timeout_seconds"] == 60.0
    assert client.closed is True


def test_runtime_requires_coordinates_when_sandbox_fallback_is_absent() -> None:
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("não deve conectar")),
    )

    result = asyncio.run(runtime._execute(_call(location="São Paulo, SP")))

    assert result.ok is False
    assert result.error == "unavailable"
    assert result.detail == "location_required"


def test_runtime_treats_mcp_error_body_as_failed_even_with_completed_tool() -> None:
    client = _FakeOpenCode(
        {
            "errors": {
                "code": "AUTHENTICATION_REQUIRED",
                "retryable": False,
            }
        }
    )
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: client,
    )

    result = asyncio.run(
        runtime._execute(_call(dietary_filters=["VEGETARIAN"]))
    )

    assert result.ok is False
    assert result.error == "unavailable"
    assert result.detail == "auth_required"
    assert result.traces == ()


def test_runtime_accepts_coordinates_from_internal_context() -> None:
    client = _FakeOpenCode({"resultKind": "ITEM", "results": []})
    client_location = {"latitude": -22.9, "longitude": -43.2}
    original_run_prompt = client.run_prompt

    async def run_prompt_with_location(session_id: str, **kwargs):
        result = await original_run_prompt(session_id, **kwargs)
        result.raw_response["parts"][0]["state"]["input"][
            "userLocation"
        ] = client_location
        return result

    client.run_prompt = run_prompt_with_location
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        client_factory=lambda: client,
    )

    result = asyncio.run(
        runtime._execute(_call(location=client_location, dietary_filters=["VEGETARIAN"]))
    )

    assert result.ok is True
    assert '"latitude": -22.9' in client.prompt_kwargs["prompt"]


def test_runtime_implements_the_published_agent_port() -> None:
    try:
        ports = import_module("backend.agents.ports")
    except ModuleNotFoundError:
        pytest.skip("a branch de agentes ainda não foi integrada nesta branch")
    client = _FakeOpenCode({"resultKind": "ITEM", "results": []})
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: client,
    )
    call = ports.RuntimeCall(
        agent_id="researcher",
        task_id="task_1",
        session_id="sess_1",
        system="Use somente ferramentas autorizadas.",
        prompt="pizza",
        output_schema={"type": "object"},
        allowed_tools=("offer_search",),
        context={"dietary_filters": ["VEGETARIAN"]},
    )

    outcome = runtime.run(call)

    assert isinstance(outcome, ports.RuntimeOutcome)
    assert isinstance(outcome.tool_calls[0], ports.ToolTrace)
    assert outcome.tool_calls[0].provider == "ifood_mcp"
