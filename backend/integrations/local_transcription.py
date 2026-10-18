"""Opt-in CPU transcription; audio stays in RAM and never goes to iFood."""
from __future__ import annotations

import asyncio
import os
import subprocess
import threading

from .errors import IntegrationError
from .transcription import TranscriptionResult


class TranscriptionError(IntegrationError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message, retryable=retryable)
        self.code = code


class LocalWhisperTranscription:
    """Requires ffmpeg and faster-whisper. One inference at a time per process."""

    def __init__(self, model: str = "small") -> None:
        self.model_name = model
        self._model = None
        self._lock = threading.Lock()

    async def transcribe(self, audio: bytes, *, content_type: str | None,
                         language: str) -> TranscriptionResult:
        if language != "pt-BR" or not audio or len(audio) > 10 * 1024 * 1024:
            raise TranscriptionError("STT_INVALID_AUDIO", "Áudio vazio, grande demais ou idioma inválido.")
        return await asyncio.to_thread(self._transcribe, audio)

    def _transcribe(self, audio: bytes) -> TranscriptionResult:
        if not self._lock.acquire(blocking=False):
            raise TranscriptionError("STT_BUSY", "Transcrição ocupada. Tente novamente.", retryable=True)
        try:
            try:
                decoded = subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "pipe",
                     "-i", "pipe:0", "-t", "121", "-vn", "-ac", "1", "-ar", "16000",
                     "-f", "f32le", "pipe:1"],
                    input=audio, capture_output=True, timeout=15, check=False,
                )
            except FileNotFoundError:
                raise TranscriptionError("STT_UNAVAILABLE", "Decodificador de áudio não instalado.") from None
            except subprocess.TimeoutExpired:
                raise TranscriptionError("STT_INVALID_AUDIO", "Não foi possível decodificar o áudio.") from None
            if decoded.returncode or not decoded.stdout:
                raise TranscriptionError("STT_INVALID_AUDIO", "Arquivo de áudio inválido.")
            if len(decoded.stdout) > 120 * 16000 * 4:
                raise TranscriptionError("STT_INVALID_AUDIO", "Envie no máximo 120 segundos de áudio.")
            try:
                import numpy as np
                from faster_whisper import WhisperModel
                if self._model is None:
                    self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                                               cpu_threads=4, num_workers=1)
                samples = np.frombuffer(decoded.stdout, dtype=np.float32)
                segments, _ = self._model.transcribe(
                    samples, language="pt", beam_size=3, vad_filter=True,
                    condition_on_previous_text=False,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
            except Exception:
                raise TranscriptionError("STT_UNAVAILABLE", "Transcrição local indisponível.",
                                         retryable=True) from None
            if not text:
                raise TranscriptionError("STT_NO_SPEECH", "Não identifiquei fala. Grave novamente.")
            return TranscriptionResult(text=text, language="pt-BR", requires_confirmation=True)
        finally:
            self._lock.release()


def transcription_from_env() -> LocalWhisperTranscription | None:
    provider = os.getenv("APP_STT_PROVIDER", "none").strip().lower()
    if provider == "none":
        return None
    if provider != "whisper":
        raise ValueError("APP_STT_PROVIDER deve ser none ou whisper")
    return LocalWhisperTranscription(os.getenv("APP_STT_MODEL", "small"))
