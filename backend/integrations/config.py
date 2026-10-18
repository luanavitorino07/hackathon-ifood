"""Configuração segura das integrações, carregada apenas do ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

IFOOD_MCP_URL = "https://consumer-mcp.ifood.com.br/marketplace"


def _positive_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("o valor precisa ser maior que zero")
    return parsed


@dataclass(frozen=True, slots=True)
class SandboxLocation:
    """Coordenadas de teste configuradas pelo backend, nunca pelo navegador."""

    latitude: float
    longitude: float
    source: Literal["sandbox", "public_test"] = "sandbox"

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude deve estar entre -90 e 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude deve estar entre -180 e 180")
        if self.source not in {"sandbox", "public_test"}:
            raise ValueError("origem da localização de teste inválida")

    @classmethod
    def from_env(cls) -> SandboxLocation | None:
        latitude = os.getenv("IFOOD_SANDBOX_LATITUDE")
        longitude = os.getenv("IFOOD_SANDBOX_LONGITUDE")
        if latitude is None and longitude is None:
            return None
        if latitude is None or longitude is None:
            raise ValueError(
                "IFOOD_SANDBOX_LATITUDE e IFOOD_SANDBOX_LONGITUDE devem ser definidos juntos"
            )
        return cls(
            latitude=float(latitude),
            longitude=float(longitude),
            source=os.getenv("IFOOD_FALLBACK_LOCATION_SOURCE", "sandbox"),
        )


@dataclass(frozen=True, slots=True)
class OpenCodeSettings:
    """Parâmetros não secretos e referências às credenciais do OpenCode."""

    base_url: str = "http://127.0.0.1:4096"
    username: str = "opencode"
    password: str | None = field(default=None, repr=False)
    provider_id: str = "google"
    model_id: str = "gemini-3.8-flash"
    model_variant: str | None = "low"
    search_tool_id: str = "ifood_searchOffers"
    request_timeout_seconds: float = 45.0
    mcp_server_name: str = "ifood"

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("OPENCODE_BASE_URL precisa usar http ou https")
        if not self.provider_id or not self.model_id:
            raise ValueError("provider_id e model_id não podem ser vazios")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds precisa ser maior que zero")

    @classmethod
    def from_env(cls) -> OpenCodeSettings:
        return cls(
            base_url=os.getenv("OPENCODE_BASE_URL", "http://127.0.0.1:4096").rstrip("/"),
            username=os.getenv("OPENCODE_SERVER_USERNAME", "opencode"),
            password=os.getenv("OPENCODE_SERVER_PASSWORD"),
            provider_id=os.getenv("OPENCODE_PROVIDER_ID", "google"),
            model_id=os.getenv("OPENCODE_MODEL_ID", "gemini-3.8-flash"),
            model_variant=os.getenv("OPENCODE_MODEL_VARIANT", "low") or None,
            search_tool_id=os.getenv("OPENCODE_IFOOD_SEARCH_TOOL_ID", "ifood_searchOffers"),
            request_timeout_seconds=_positive_float(
                os.getenv("OPENCODE_REQUEST_TIMEOUT_SECONDS"), 45.0
            ),
            mcp_server_name=os.getenv("OPENCODE_IFOOD_MCP_NAME", "ifood"),
        )


def build_ifood_mcp_config() -> dict[str, object]:
    """Retorna configuração segura para injeção no OpenCode.

    Os valores permanecem como referências de ambiente. Esta função nunca lê,
    retorna ou registra os segredos propriamente ditos.
    """

    return {
        "type": "remote",
        "url": IFOOD_MCP_URL,
        "enabled": True,
        "oauth": {
            "clientId": "{env:IFOOD_MCP_CLIENT_ID}",
            "clientSecret": "{env:IFOOD_MCP_CLIENT_SECRET}",
            "scope": "mcp.discovery.search.read",
        },
    }
