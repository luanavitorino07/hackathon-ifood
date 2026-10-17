"""Cliente HTTP assíncrono e estreito para o OpenCode Server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Self

import httpx

from .config import OpenCodeSettings
from .errors import (
    InvalidOutputError,
    QuotaError,
    RuntimeTimeoutError,
    UnavailableError,
)


@dataclass(frozen=True, slots=True)
class OpenCodeHealth:
    healthy: bool
    version: str


@dataclass(frozen=True, slots=True)
class OpenCodeRunResult:
    session_id: str
    message_id: str | None
    structured_output: Any
    raw_response: dict[str, Any]


class OpenCodeClient:
    """Encapsula apenas endpoints documentados do OpenCode Server."""

    def __init__(
        self,
        settings: OpenCodeSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        auth = None
        if settings.password:
            auth = httpx.BasicAuth(settings.username, settings.password)
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            auth=auth,
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> OpenCodeHealth:
        data = await self._request_json("GET", "/global/health")
        healthy = data.get("healthy")
        version = data.get("version")
        if healthy is not True or not isinstance(version, str) or not version:
            raise InvalidOutputError("resposta de saúde inválida do OpenCode")
        return OpenCodeHealth(healthy=True, version=version)

    async def create_session(self, *, title: str | None = None) -> str:
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        data = await self._request_json("POST", "/session", json=body)
        session_id = data.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise InvalidOutputError("OpenCode não devolveu um identificador de sessão")
        return session_id

    async def run_prompt(
        self,
        session_id: str,
        *,
        prompt: str,
        agent: str | None = None,
        tools: Mapping[str, bool] | None = None,
        output_schema: Mapping[str, Any] | None = None,
    ) -> OpenCodeRunResult:
        if not session_id or not prompt.strip():
            raise ValueError("session_id e prompt são obrigatórios")
        body: dict[str, Any] = {
            "model": {
                "providerID": self.settings.provider_id,
                "modelID": self.settings.model_id,
            },
            "parts": [{"type": "text", "text": prompt}],
        }
        if agent:
            body["agent"] = agent
        if tools is not None:
            body["tools"] = dict(tools)
        if output_schema is not None:
            body["format"] = {
                "type": "json_schema",
                "schema": dict(output_schema),
                "retryCount": 1,
            }

        data = await self._request_json(
            "POST", f"/session/{session_id}/message", json=body
        )
        info = data.get("info")
        if not isinstance(info, Mapping):
            raise InvalidOutputError("resposta de mensagem inválida do OpenCode")
        error = info.get("error")
        if isinstance(error, Mapping) and error.get("name") == "StructuredOutputError":
            raise InvalidOutputError("Gemini não produziu a saída estruturada esperada")
        message_id = info.get("id")
        if message_id is not None and not isinstance(message_id, str):
            raise InvalidOutputError("identificador de mensagem inválido do OpenCode")
        return OpenCodeRunResult(
            session_id=session_id,
            message_id=message_id,
            structured_output=info.get("structured_output"),
            raw_response=data,
        )

    async def abort_session(self, session_id: str) -> bool:
        data = await self._request_json("POST", f"/session/{session_id}/abort")
        if not isinstance(data, bool):
            raise InvalidOutputError("resposta de cancelamento inválida do OpenCode")
        return data

    async def mcp_status(self) -> dict[str, Any]:
        data = await self._request_json("GET", "/mcp")
        return data

    async def list_tool_ids(self) -> list[str]:
        data = await self._request_json("GET", "/experimental/tool/ids")
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise InvalidOutputError("lista de ferramentas inválida do OpenCode")
        return data

    async def list_tools(self) -> Any:
        return await self._request_json(
            "GET",
            "/experimental/tool",
            params={
                "provider": self.settings.provider_id,
                "model": self.settings.model_id,
            },
        )

    async def iter_events(self) -> AsyncIterator[dict[str, Any]]:
        """Converte o SSE interno do OpenCode em objetos JSON."""

        try:
            async with self._client.stream("GET", "/event") as response:
                self._raise_for_status(response)
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        if data_lines:
                            yield _decode_sse_data(data_lines)
                            data_lines.clear()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                if data_lines:
                    yield _decode_sse_data(data_lines)
        except httpx.TimeoutException as exc:
            raise RuntimeTimeoutError("tempo limite do stream do OpenCode excedido") from exc
        except httpx.RequestError as exc:
            raise UnavailableError("não foi possível conectar ao OpenCode") from exc

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
            self._raise_for_status(response)
        except httpx.TimeoutException as exc:
            raise RuntimeTimeoutError("tempo limite da chamada ao OpenCode excedido") from exc
        except httpx.RequestError as exc:
            raise UnavailableError("não foi possível conectar ao OpenCode") from exc

        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise InvalidOutputError("OpenCode devolveu JSON inválido") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 429:
            raise QuotaError("cota do provedor de IA temporariamente excedida")
        if response.status_code in {408, 504}:
            raise RuntimeTimeoutError("tempo limite da chamada ao OpenCode excedido")
        if response.status_code >= 500:
            raise UnavailableError("OpenCode está temporariamente indisponível")
        if response.status_code >= 400:
            raise UnavailableError(
                f"OpenCode rejeitou a solicitação com status {response.status_code}",
                retryable=False,
            )


def _decode_sse_data(lines: list[str]) -> dict[str, Any]:
    try:
        value = json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        raise InvalidOutputError("evento SSE inválido do OpenCode") from exc
    if not isinstance(value, dict):
        raise InvalidOutputError("evento SSE do OpenCode precisa ser um objeto")
    return value
