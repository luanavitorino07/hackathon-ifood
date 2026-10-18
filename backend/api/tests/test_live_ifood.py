"""Opt-in: valida uma API local já iniciada, com agentes e MCP reais."""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_IFOOD") != "1",
    reason="exige API em modo real, Gemini e OAuth iFood; RUN_LIVE_IFOOD=1 habilita",
)


def test_real_api_recommendations_history_and_customer_sse():
    base_url = os.getenv("LIVE_IFOOD_API_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        created = client.post("/api/v1/sessions", json={"client_id": None})
        assert created.status_code == 201
        assert created.json()["mode"] == "real", "Não aceitar demo como prova de integração"
        sid = created.json()["session_id"]
        accepted = client.post(
            "/api/v1/chat/messages",
            json={
                "session_id": sid,
                "client_message_id": "smoke_1",
                "text": "Quero pizza para 1 pessoa até R$ 200",
                "input_mode": "text",
                "transcription_id": None,
            },
        )
        assert accepted.status_code == 202
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline:
            snapshot = client.get(f"/api/v1/sessions/{sid}/snapshot").json()
            if any(m["role"] == "assistant" for m in snapshot["messages"]):
                break
            time.sleep(0.5)
        assert snapshot["recommendations"], "A busca real não produziu recomendações"
        assert all(r["data_origin"] == "ifood_mcp" for r in snapshot["recommendations"])
        assert snapshot["agents"] == []
        history = client.get(f"/api/v1/sessions/{sid}/history?limit=200").json()["events"]
        assert not any(e["visibility"] == "admin" or e["type"] == "error" for e in history)
        received = []
        with client.stream("GET", f"/api/v1/sessions/{sid}/events") as stream:
            assert stream.status_code == 200
            for line in stream.iter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
                    if len(received) == len(history):
                        break
        assert received == history
