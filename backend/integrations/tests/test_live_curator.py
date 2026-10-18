"""Opt-in: real OpenCode reasoning with synthetic items, without an iFood search."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

from backend.agents.curator import SCHEMA, SYSTEM
from backend.agents.ports import RuntimeCall
from backend.integrations.agent_runtime import OpenCodeAgentRuntime
from backend.integrations.config import OpenCodeSettings
from backend.integrations.opencode_client import OpenCodeClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_OPENCODE") != "1",
    reason="consome uma chamada de IA real; RUN_LIVE_OPENCODE=1 habilita",
)


def test_real_curator_distinguishes_dish_from_flavor_and_reports_usage():
    measurements = []

    class MeasuredClient(OpenCodeClient):
        async def run_prompt(self, session_id, **kwargs):
            try:
                result = await super().run_prompt(session_id, **kwargs)
            except Exception as exc:
                print("Live OpenCode call failed: " + type(exc).__name__)
                raise
            info = result.raw_response.get("info", {})
            measurements.append({
                "agent": info.get("agent"),
                "tokens": info.get("tokens"),
                "cost": info.get("cost"),
                "tools": [
                    part.get("tool") for part in result.raw_response.get("parts", [])
                    if part.get("type") == "tool"
                ],
            })
            return result

    settings = OpenCodeSettings.from_env()
    items = [
        {"product_id": "pizza", "item": "Pizza Grande Margherita 8 fatias",
         "restaurante": "Pizzaria Teste", "preco_unitario": "R$ 49.90"},
        {"product_id": "pastel", "item": "Pastel de Pizza",
         "restaurante": "Pastelaria Teste", "preco_unitario": "R$ 12.00"},
        {"product_id": "esfiha", "item": "Esfiha sabor Pizza",
         "restaurante": "Esfiharia Teste", "preco_unitario": "R$ 8.99"},
        {"product_id": "flavor", "item": "Pizza",
         "restaurante": "Esfiharia Teste", "preco_unitario": "R$ 8.99"},
    ]
    runtime = OpenCodeAgentRuntime(settings, client_factory=lambda: MeasuredClient(settings))
    outcome = runtime.run(RuntimeCall(
        agent_id="curator", task_id="live_curator_regression", session_id="synthetic_smoke",
        system=SYSTEM,
        prompt='Pedido do cliente: Quero pizza grande para 2 pessoas\nPRATO_JSON: ["pizza"]\n'
               'Pessoas: 2; restrições: []\nITENS_JSON: ' + json.dumps(items, ensure_ascii=False),
        output_schema=SCHEMA, allowed_tools=(), max_tool_calls=0, timeout_s=40,
    ))
    assert outcome.ok, f"{outcome.error}: {outcome.detail}"
    assert outcome.tool_calls == ()
    fits = {item["product_id"]: item["fit"] for item in outcome.structured["items"]}
    assert fits == {"pizza": "sim", "pastel": "nao", "esfiha": "nao", "flavor": "nao"}
    assert measurements[0]["agent"] == settings.reasoning_agent
    assert set(measurements[0]["tools"]) <= {"StructuredOutput"}
    print("OpenCode live reasoning usage: " + json.dumps(measurements))


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_IFOOD") != "1",
    reason="exige busca iFood real além do raciocínio; RUN_LIVE_IFOOD=1 habilita",
)
def test_real_api_search_and_curator_keep_only_approved_products():
    from backend.api.main import build_application
    from backend.integrations.config import SAO_CARLOS_TEST_COORDINATES, SandboxLocation

    measurements = []
    judgments = []

    class MeasuredClient(OpenCodeClient):
        async def run_prompt(self, session_id, **kwargs):
            result = await super().run_prompt(session_id, **kwargs)
            info = result.raw_response.get("info", {})
            measurements.append({
                "agent": info.get("agent"), "tokens": info.get("tokens"),
                "cost": info.get("cost"),
            })
            if "Curador" in (kwargs.get("system") or ""):
                judgments.append(result.structured_output)
            return result

    settings = OpenCodeSettings.from_env()
    runtime = OpenCodeAgentRuntime(
        settings,
        sandbox_location=SandboxLocation(*SAO_CARLOS_TEST_COORDINATES, source="public_test"),
        include_closed_for_testing=True,
        client_factory=lambda: MeasuredClient(settings),
    )
    app = build_application(runtime=runtime, runtime_mode="real", memory_backend="ephemeral")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test", timeout=180
        ) as client:
            session_id = (
                await client.post("/api/v1/sessions", json={"client_id": None})
            ).json()["session_id"]
            sent = await client.post("/api/v1/chat/messages", json={
                "session_id": session_id, "client_message_id": "live_fix_validation",
                "text": "Quero pizza para 2 pessoas até R$ 150",
                "input_mode": "text", "transcription_id": None,
            })
            assert sent.status_code == 202
            snapshot = (await client.get(f"/api/v1/sessions/{session_id}/snapshot")).json()
            if not judgments:
                history = (
                    await client.get(f"/api/v1/sessions/{session_id}/history?limit=200")
                ).json()["events"]
                print("Live API error codes: " + json.dumps([
                    event["payload"]["code"] for event in history if event["type"] == "error"
                ]))
            assert judgments and isinstance(judgments[0], dict), "Curador real não respondeu"
            fits = {item["product_id"]: item["fit"] for item in judgments[0]["items"]}
            assert fits, "A busca real não forneceu itens para o Curador"
            accepted = {key for key, fit in fits.items() if fit == "sim"}
            recommended = {
                item["product_id"] for rec in snapshot["recommendations"] for item in rec["items"]
            }
            if accepted:
                assert recommended and recommended <= accepted
            else:
                assert not recommended
            assert all(rec["data_origin"] == "ifood_mcp" for rec in snapshot["recommendations"])
            print("Live API curation: " + json.dumps({
                "judged": len(fits), "accepted": len(accepted),
                "rejected": sum(fit == "nao" for fit in fits.values()),
                "recommended": len(recommended),
            }))

    asyncio.run(scenario())
    print("Live API usage: " + json.dumps(measurements))
