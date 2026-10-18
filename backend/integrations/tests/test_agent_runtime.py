from __future__ import annotations

import asyncio
import json
from importlib import import_module
from types import SimpleNamespace

import pytest

from backend.integrations.agent_runtime import OpenCodeAgentRuntime
from backend.integrations.config import OpenCodeSettings, SandboxLocation
from backend.integrations.errors import QuotaError, RuntimeTimeoutError
from backend.integrations.opencode_client import OpenCodeRunResult


class _FakeOpenCode:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.closed = False
        self.prompt_kwargs = None

    async def list_tool_ids(self) -> list[str]:
        return ["bash", "ifood_searchOffers"]

    async def create_session(
        self,
        *,
        title: str | None = None,
        allow_search: bool = True,
    ) -> str:
        assert title == "researcher:task_1"
        assert allow_search is True
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
                                "refinements": {
                                    "onlyOpen": "refinements.onlyOpen=true" in kwargs["prompt"],
                                    **(
                                        {"itemRestrictions": ["VEGETARIAN"]}
                                        if "Use refinements.itemRestrictions=" in kwargs["prompt"]
                                        else {}
                                    ),
                                },
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


class _ReasoningOpenCode:
    def __init__(self, structured=None, error: Exception | None = None) -> None:
        self.structured = structured
        self.error = error
        self.create_kwargs = None
        self.prompt_kwargs = None
        self.closed = False
        self.aborted = []

    async def list_tool_ids(self):
        raise AssertionError("raciocínio não deve consultar o catálogo de ferramentas")

    async def create_session(self, **kwargs):
        self.create_kwargs = kwargs
        return "reasoning_session"

    async def run_prompt(self, session_id, **kwargs):
        assert session_id == "reasoning_session"
        self.prompt_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return OpenCodeRunResult(
            session_id=session_id,
            message_id="reasoning_message",
            structured_output=self.structured,
            raw_response={"info": {"id": "reasoning_message"}, "parts": []},
        )

    async def abort_session(self, session_id):
        self.aborted.append(session_id)
        return True

    async def aclose(self):
        self.closed = True


def _reasoning_call():
    return SimpleNamespace(
        agent_id="curator",
        task_id="task_1",
        session_id="sess_1",
        system="Julgue os itens.",
        prompt="Retorne JSON.",
        output_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        allowed_tools=(),
        max_tool_calls=0,
        timeout_s=40.0,
        context={},
    )


def test_runtime_executes_structured_reasoning_without_tools() -> None:
    client = _ReasoningOpenCode({"answer": "ok"})
    runtime = OpenCodeAgentRuntime(OpenCodeSettings(), client_factory=lambda: client)

    result = asyncio.run(runtime._execute(_reasoning_call()))

    assert result.ok is True
    assert result.structured == {"answer": "ok"}
    assert result.traces == ()
    assert client.create_kwargs == {"title": "curator:task_1", "allow_search": False}
    assert client.prompt_kwargs["tools"] == {"*": False}
    assert client.prompt_kwargs["output_schema"] == _reasoning_call().output_schema
    assert client.prompt_kwargs["timeout_seconds"] == 40.0
    assert client.closed is True


def test_runtime_rejects_invalid_structured_reasoning_output() -> None:
    client = _ReasoningOpenCode(None)
    runtime = OpenCodeAgentRuntime(OpenCodeSettings(), client_factory=lambda: client)

    result = asyncio.run(runtime._execute(_reasoning_call()))

    assert result.ok is False
    assert result.error == "invalid_output"
    assert result.detail == "invalid_model_output"
    assert client.closed is True


@pytest.mark.parametrize(
    "error,expected,retry_after,aborted",
    [
        (QuotaError("quota"), "quota", 30, []),
        (RuntimeTimeoutError("timeout"), "timeout", None, ["reasoning_session"]),
    ],
)
def test_runtime_normalizes_reasoning_provider_failures(error, expected, retry_after, aborted):
    client = _ReasoningOpenCode(error=error)
    runtime = OpenCodeAgentRuntime(OpenCodeSettings(), client_factory=lambda: client)

    result = asyncio.run(runtime._execute(_reasoning_call()))

    assert result.ok is False
    assert result.error == expected
    assert result.retry_after_s == retry_after
    assert client.aborted == aborted
    assert client.closed is True


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

    result = asyncio.run(
        runtime._execute(
            _call(
                location="São Paulo, SP",
                dietary_filters=["VEGETARIAN"],
            )
        )
    )

    assert result.ok is True
    assert result.structured == {
        "offers": [
            {
                "product_id": "item_1",
                "name": "Pizza Margherita",
                "unit_price_cents": 2900,
                    "original_unit_price_cents": 3290,
                    "image_url": None,
                "merchant_id": "merchant_1",
                "merchant_name": "Pizza Express",
                "tags": [],
                "delivery_fee_cents": 0,
                "other_fees_cents": None,
                "eta_minutes": 45,
                    "eta_min_minutes": 30,
                    "distance_km": None,
                    "merchant_rating": None,
                    "_merchant_is_open": None,
            }
        ]
    }
    assert result.traces[0].provider == "ifood_mcp"
    assert result.traces[0].status == "succeeded"
    assert result.detail == "sandbox_location_used"
    assert "Localização de sandbox utilizada" in result.traces[0].summary
    assert client.prompt_kwargs["tools"] == {
        "*": False,
        "bash": False,
        "ifood_searchOffers": True,
    }
    assert '"latitude": -23.55' in client.prompt_kwargs["prompt"]
    assert client.prompt_kwargs["timeout_seconds"] == 60.0
    assert client.closed is True


def test_runtime_can_include_closed_merchants_only_in_explicit_test_mode() -> None:
    from backend.integrations.search_quality import CLOSED_TEST_ONLY, CLOSED_TEST_TAG

    payload = {
        "resultKind": "ITEM",
        "results": [
            {
                "itemId": "closed_item",
                "itemName": "Pizza de teste",
                "unitPrice": 20,
                "merchant": {
                    "merchantId": "closed_merchant",
                    "merchantName": "Loja fechada",
                    "isOpen": False,
                    "deliveryMethod": {"fee": 0},
                },
            }
        ],
    }
    client = _FakeOpenCode(payload)
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: client,
        include_closed_for_testing=True,
    )

    result = asyncio.run(runtime._execute(_call()))

    assert result.ok is True
    offer = result.structured["offers"][0]
    assert offer["product_id"] == "closed_item"
    assert offer["tags"] == [CLOSED_TEST_TAG]
    assert "is_open" not in offer
    assert "refinements.onlyOpen=false" in client.prompt_kwargs["prompt"]
    assert "restaurantes fechados podem ser exibidos" in result.traces[0].summary
    assert CLOSED_TEST_ONLY in runtime.recommendation_warnings(
        "sess_1", "closed_merchant", ["closed_item"]
    )


def test_runtime_requires_coordinates_when_sandbox_fallback_is_absent() -> None:
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("não deve conectar")),
    )

    result = asyncio.run(runtime._execute(_call(location="São Paulo, SP")))

    assert result.ok is False
    assert result.error == "unavailable"
    assert result.detail == "location_required"


def test_runtime_uses_sao_carlos_preset_in_actual_tool_prompt(monkeypatch) -> None:
    from backend.integrations.config import SAO_CARLOS_TEST_COORDINATES

    monkeypatch.delenv("IFOOD_SANDBOX_LATITUDE", raising=False)
    monkeypatch.delenv("IFOOD_SANDBOX_LONGITUDE", raising=False)
    monkeypatch.setenv("IFOOD_TEST_LOCATION", "sao_carlos")
    location = SandboxLocation.from_env()
    client = _FakeOpenCode({"resultKind": "ITEM", "results": []})
    original_prompt = client.run_prompt

    async def matching_tool_result(session_id, **kwargs):
        response = await original_prompt(session_id, **kwargs)
        response.raw_response["parts"][0]["state"]["input"]["userLocation"] = {
            "latitude": location.latitude,
            "longitude": location.longitude,
        }
        return response

    client.run_prompt = matching_tool_result
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=location,
        client_factory=lambda: client,
    )
    result = asyncio.run(runtime._execute(_call(location="São Carlos, SP")))
    assert result.ok is True
    latitude, longitude = SAO_CARLOS_TEST_COORDINATES
    assert f'"latitude": {latitude}' in client.prompt_kwargs["prompt"]
    assert f'"longitude": {longitude}' in client.prompt_kwargs["prompt"]
    assert "-23.5505" not in client.prompt_kwargs["prompt"]
    assert result.detail == "test_location_used"
    assert "não é a localização do cliente" in result.traces[0].summary


def test_customer_coordinates_override_public_test_preset():
    from backend.integrations.agent_runtime import _resolve_location
    from backend.integrations.config import SAO_CARLOS_TEST_COORDINATES

    resolved = _resolve_location(
        {"location": {"latitude": -20.0, "longitude": -40.0}},
        SandboxLocation(*SAO_CARLOS_TEST_COORDINATES, source="public_test"),
    )
    assert resolved.source == "context"
    assert resolved.coordinates == {"latitude": -20.0, "longitude": -40.0}


def test_timed_out_execution_is_aborted_and_client_closed() -> None:
    client = _FakeOpenCode({})
    aborted = []

    async def timeout(session_id, **kwargs):
        raise RuntimeTimeoutError("timeout")

    async def abort(session_id):
        aborted.append(session_id)
        return True

    client.run_prompt = timeout
    client.abort_session = abort
    runtime = OpenCodeAgentRuntime(
        OpenCodeSettings(),
        sandbox_location=SandboxLocation(-23.55, -46.63),
        client_factory=lambda: client,
    )
    result = asyncio.run(runtime._execute(_call()))
    assert result.error == "timeout"
    assert aborted == ["oc_session_1"]
    assert client.closed


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

    result = asyncio.run(runtime._execute(_call(dietary_filters=["VEGETARIAN"])))

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
        result.raw_response["parts"][0]["state"]["input"]["userLocation"] = client_location
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
    assert result.detail is None
    assert "sandbox" not in result.traces[0].summary.lower()
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
