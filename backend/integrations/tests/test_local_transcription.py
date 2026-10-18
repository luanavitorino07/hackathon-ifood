import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from backend.api.main import build_application
from backend.integrations.local_transcription import LocalWhisperTranscription, TranscriptionError


def test_missing_provider_keeps_existing_contract(monkeypatch):
    monkeypatch.setenv("APP_STT_PROVIDER", "none")
    app = build_application(runtime_mode="demo", memory_backend="ephemeral")
    assert app.state.transcription_provider is None


def test_invalid_audio_does_not_load_model():
    provider = LocalWhisperTranscription()
    with pytest.raises(TranscriptionError, match="inválido"):
        asyncio.run(provider.transcribe(b"not audio", content_type="audio/wav", language="pt-BR"))
    assert provider._model is None


def test_duration_limit_before_model_load():
    provider = LocalWhisperTranscription()
    decoded = SimpleNamespace(returncode=0, stdout=b"\0" * (121 * 16000 * 4))
    with patch("backend.integrations.local_transcription.subprocess.run", return_value=decoded):
        with pytest.raises(TranscriptionError, match="120 segundos"):
            asyncio.run(provider.transcribe(b"audio", content_type="audio/wav", language="pt-BR"))
    assert provider._model is None


def test_busy_does_not_start_second_inference():
    provider = LocalWhisperTranscription()
    provider._lock.acquire()
    try:
        with pytest.raises(TranscriptionError) as error:
            asyncio.run(provider.transcribe(b"audio", content_type="audio/wav", language="pt-BR"))
        assert error.value.code == "STT_BUSY"
    finally:
        provider._lock.release()


def test_http_browser_mime_and_confirmation_contract(monkeypatch):
    monkeypatch.setenv("APP_STT_PROVIDER", "whisper")
    app = build_application(runtime_mode="demo", memory_backend="ephemeral")
    from backend.integrations.transcription import TranscriptionResult
    calls = []

    async def transcribe(audio, **kwargs):
        calls.append(kwargs)
        return TranscriptionResult("Quero pizza sem cebola.", "pt-BR")

    app.state.transcription_provider.transcribe = transcribe

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
            result = await c.post("/api/v1/audio/transcriptions", files={
                "audio": ("voice.webm", b"test", "audio/webm;codecs=opus")})
            assert result.status_code == 200
            data = result.json()
            assert set(data) == {"schema_version", "transcription_id", "text", "language", "requires_confirmation"}
            assert data["requires_confirmation"] is True
            assert data["language"] == "pt-BR"
            assert not app.state.backend_state._records
            sid = (await c.post("/api/v1/sessions", json={"client_id": None})).json()["session_id"]
            sent = await c.post("/api/v1/chat/messages", json={
                "session_id": sid, "client_message_id": "confirmed_audio",
                "text": "Olá", "input_mode": "audio",
                "transcription_id": data["transcription_id"],
            })
            assert sent.status_code == 202
            snapshot = (await c.get(f"/api/v1/sessions/{sid}/snapshot")).json()
            assert snapshot["messages"][0]["input_mode"] == "audio"
            assert snapshot["messages"][0]["text"] == "Olá"
    asyncio.run(scenario())
    assert calls == [{"content_type": "audio/webm", "language": "pt-BR"}]
