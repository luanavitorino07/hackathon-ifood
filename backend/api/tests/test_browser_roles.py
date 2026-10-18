"""Buyer and office live in one local browser without sharing visibility."""
from fastapi.testclient import TestClient

from backend.api.main import build_application


def test_buyer_stays_customer_after_manager_cookie():
    app = build_application(runtime_mode="demo", memory_backend="ephemeral")
    with TestClient(app) as client:
        admin = {"X-Demo-Role": "admin"}
        buyer = {"X-Demo-Role": "customer"}
        assert client.get("/api/v1/admin/overview", headers=admin).status_code == 200
        assert client.cookies.get("ifood_local_demo_admin")
        assert client.get("/api/v1/agents", headers=buyer).status_code == 403
        created = client.post("/api/v1/sessions", headers=buyer, json={"client_id": None})
        assert created.status_code == 201
        sid = created.json()["session_id"]
        sent = client.post("/api/v1/chat/messages", headers=buyer, json={
            "session_id": sid, "client_message_id": "same_browser", "text": "Quero pizza até R$ 100",
            "input_mode": "text", "transcription_id": None,
        })
        assert sent.status_code == 202
        private = client.get(f"/api/v1/sessions/{sid}/history", headers=admin).json()
        public = client.get(f"/api/v1/sessions/{sid}/history", headers=buyer).json()
        assert any(e["type"] == "agent_message" for e in private["events"])
        assert all(e["visibility"] != "admin" for e in public["events"])
        assert client.get(f"/api/v1/sessions/{sid}/snapshot", headers=buyer).json()["agents"] == []
