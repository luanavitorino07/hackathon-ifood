"""Fronteira local de STT; nenhum provedor foi escolhido para o MVP ainda."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    language: str
    requires_confirmation: bool = True


class TranscriptionProvider(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str | None,
        language: str,
    ) -> TranscriptionResult: ...
