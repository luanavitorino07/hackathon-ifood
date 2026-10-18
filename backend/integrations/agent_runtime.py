"""Implementação da porta dos agentes sobre OpenCode + MCP do iFood.

O módulo importa os tipos de ``backend.agents`` apenas ao materializar o
``RuntimeOutcome``. Assim, a branch de integrações não copia nem redefine o
contrato que pertence ao módulo de agentes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from importlib import import_module
from time import monotonic
from typing import Any, Protocol

from .config import OpenCodeSettings, SandboxLocation
from .errors import (
    IntegrationError,
    InvalidOutputError,
    QuotaError,
    RuntimeTimeoutError,
    UnavailableError,
)
from .opencode_client import OpenCodeClient, OpenCodeRunResult

_LOGICAL_TOOL = "offer_search"
_MCP_TOOL_SUFFIX = "searchoffers"
_DIETARY_FILTERS = frozenset({"VEGETARIAN", "VEGAN", "GLUTEN_FREE"})


class _RuntimeCallLike(Protocol):
    agent_id: str
    task_id: str
    session_id: str
    system: str
    prompt: str
    allowed_tools: tuple[str, ...]
    max_tool_calls: int
    timeout_s: float
    context: dict[str, Any]


class _OpenCodePort(Protocol):
    async def list_tool_ids(self) -> list[str]: ...

    async def create_session(self, *, title: str | None = None) -> str: ...

    async def run_prompt(
        self,
        session_id: str,
        *,
        prompt: str,
        system: str | None = None,
        agent: str | None = None,
        tools: Mapping[str, bool] | None = None,
        output_schema: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> OpenCodeRunResult: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _TraceData:
    call_id: str
    tool_name: str
    provider: str
    status: str
    duration_ms: int | None
    summary: str


@dataclass(frozen=True, slots=True)
class _ExecutionResult:
    ok: bool
    structured: dict[str, Any] | None = None
    traces: tuple[_TraceData, ...] = ()
    error: str | None = None
    retry_after_s: int | None = None
    detail: str | None = None


class OpenCodeAgentRuntime:
    """Implementa estruturalmente ``AgentRuntimePort.run``.

    A saída estruturada é montada da resposta bruta da tool MCP registrada no
    OpenCode. Texto livre ou JSON produzido apenas pelo modelo não promove a
    origem para ``ifood_mcp``.
    """

    def __init__(
        self,
        settings: OpenCodeSettings,
        *,
        sandbox_location: SandboxLocation | None = None,
        client_factory: Callable[[], _OpenCodePort] | None = None,
    ) -> None:
        self._settings = settings
        self._sandbox_location = sandbox_location
        self._client_factory = client_factory or (lambda: OpenCodeClient(settings))

    def run(self, call: _RuntimeCallLike) -> Any:
        """Executa a chamada síncrona exigida por ``AgentRuntimePort``."""

        result = asyncio.run(self._execute(call))
        ports = import_module("backend.agents.ports")
        traces = tuple(
            ports.ToolTrace(
                trace.call_id,
                trace.tool_name,
                trace.provider,
                trace.status,
                trace.duration_ms,
                trace.summary,
            )
            for trace in result.traces
        )
        return ports.RuntimeOutcome(
            ok=result.ok,
            structured=result.structured,
            tool_calls=traces,
            error=result.error,
            retry_after_s=result.retry_after_s,
            detail=result.detail,
        )

    async def _execute(self, call: _RuntimeCallLike) -> _ExecutionResult:
        if _LOGICAL_TOOL not in call.allowed_tools:
            return _failure("invalid_output", "tool_not_allowed")
        if call.max_tool_calls < 1:
            return _failure("invalid_output", "tool_call_limit")

        location = _resolve_location(call.context, self._sandbox_location)
        if location is None:
            return _failure("unavailable", "location_required")
        dietary = _read_dietary_filters(call.context)
        client = self._client_factory()
        started_at = monotonic()
        try:
            tool_ids = await client.list_tool_ids()
            tool_id = _resolve_search_tool(tool_ids, self._settings.mcp_server_name)
            enabled_tools = {item: item == tool_id for item in tool_ids}
            session_id = await client.create_session(
                title=f"{call.agent_id}:{call.task_id}"[:120]
            )
            response = await client.run_prompt(
                session_id,
                system=call.system,
                prompt=_build_search_prompt(call.prompt, location, dietary),
                tools=enabled_tools,
                timeout_seconds=call.timeout_s,
            )
            part = _completed_tool_part(
                response.raw_response,
                tool_id=tool_id,
                max_tool_calls=call.max_tool_calls,
            )
            payload = _tool_payload(part)
            _raise_mcp_error(payload)
            _validate_tool_input(part, location=location, dietary=dietary)
            offers = _map_offers(payload)
            duration_ms = _tool_duration_ms(part)
            if duration_ms is None:
                duration_ms = max(0, round((monotonic() - started_at) * 1000))
            call_id = part.get("callID") or part.get("id")
            if not isinstance(call_id, str) or not call_id:
                raise InvalidOutputError("missing_call_id")
            trace = _TraceData(
                call_id=call_id,
                tool_name=_LOGICAL_TOOL,
                provider="ifood_mcp",
                status="succeeded",
                duration_ms=duration_ms,
                summary=f"Busca MCP concluída com {len(offers)} oferta(s).",
            )
            return _ExecutionResult(
                ok=True,
                structured={"offers": offers},
                traces=(trace,),
            )
        except IntegrationError as exc:
            retry_after = 30 if isinstance(exc, QuotaError) else None
            return _failure(exc.code, _safe_detail(exc), retry_after_s=retry_after)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return _failure("invalid_output", "invalid_mcp_response")
        finally:
            await client.aclose()


def _failure(
    error: str,
    detail: str,
    *,
    retry_after_s: int | None = None,
) -> _ExecutionResult:
    return _ExecutionResult(
        ok=False,
        error=error,
        retry_after_s=retry_after_s,
        detail=detail,
    )


def _safe_detail(exc: IntegrationError) -> str:
    allowed = {
        "auth_required",
        "invalid_mcp_response",
        "invalid_query",
        "location_required",
        "mcp_error",
        "service_unavailable",
        "tool_ambiguous",
        "tool_failed",
        "tool_not_called",
        "tool_unavailable",
    }
    value = str(exc)
    if value in allowed:
        return value
    if isinstance(exc, QuotaError):
        return "quota_exceeded"
    if isinstance(exc, RuntimeTimeoutError):
        return "runtime_timeout"
    if isinstance(exc, InvalidOutputError):
        return "invalid_mcp_response"
    return "runtime_unavailable"


def _resolve_location(
    context: Mapping[str, Any], fallback: SandboxLocation | None
) -> dict[str, float] | None:
    raw = context.get("location")
    if isinstance(raw, Mapping):
        latitude = raw.get("latitude")
        longitude = raw.get("longitude")
        if _coordinate(latitude, -90, 90) and _coordinate(longitude, -180, 180):
            return {"latitude": float(latitude), "longitude": float(longitude)}
    if fallback is not None:
        return {"latitude": fallback.latitude, "longitude": fallback.longitude}
    return None


def _coordinate(value: Any, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and minimum <= float(value) <= maximum
    )


def _read_dietary_filters(context: Mapping[str, Any]) -> list[str]:
    raw = context.get("dietary_filters")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return sorted({item for item in raw if isinstance(item, str) and item in _DIETARY_FILTERS})


def _resolve_search_tool(tool_ids: Sequence[str], server_name: str) -> str:
    candidates = [item for item in tool_ids if _compact(item).endswith(_MCP_TOOL_SUFFIX)]
    server = _compact(server_name)
    preferred = [item for item in candidates if server and server in _compact(item)]
    if len(preferred) == 1:
        return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise UnavailableError("tool_unavailable", retryable=False)
    raise UnavailableError("tool_ambiguous", retryable=False)


def _compact(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _build_search_prompt(
    agent_prompt: str,
    location: Mapping[str, float],
    dietary: Sequence[str],
) -> str:
    dietary_instruction = (
        f"Use refinements.dietary={json.dumps(list(dietary))}. "
        if dietary
        else "Não envie refinements.dietary. "
    )
    return (
        "Execute exatamente uma chamada à tool searchOffers do MCP do iFood. "
        "Busque itens (resultKind ITEM), nunca merchants. Use exatamente "
        f"userLocation={json.dumps(dict(location), ensure_ascii=False)}. "
        f"{dietary_instruction}"
        "Não use localização inferida e não chame outras tools. Pedido:\n"
        f"{agent_prompt}"
    )


def _completed_tool_part(
    raw_response: Mapping[str, Any], *, tool_id: str, max_tool_calls: int
) -> Mapping[str, Any]:
    parts = raw_response.get("parts")
    if not isinstance(parts, list):
        raise InvalidOutputError("invalid_mcp_response")
    tool_parts = [
        part
        for part in parts
        if isinstance(part, Mapping) and part.get("type") == "tool"
    ]
    if len(tool_parts) > max_tool_calls:
        raise InvalidOutputError("invalid_mcp_response")
    matching = [
        part
        for part in tool_parts
        if (part.get("tool") or part.get("name")) == tool_id
    ]
    if not matching:
        raise UnavailableError("tool_not_called", retryable=False)
    part = matching[-1]
    state = part.get("state")
    if not isinstance(state, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    status = state.get("status")
    if status == "error":
        raise UnavailableError("tool_failed")
    if status != "completed":
        raise UnavailableError("tool_not_called")
    return part


def _validate_tool_input(
    part: Mapping[str, Any],
    *,
    location: Mapping[str, float],
    dietary: Sequence[str],
) -> None:
    state = part.get("state")
    if not isinstance(state, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    tool_input = state.get("input")
    if not isinstance(tool_input, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    query = tool_input.get("query")
    if not isinstance(query, str) or not query.strip():
        raise InvalidOutputError("invalid_query")
    if tool_input.get("resultKind") != "ITEM":
        raise InvalidOutputError("invalid_mcp_response")
    actual_location = tool_input.get("userLocation")
    if not isinstance(actual_location, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    for coordinate in ("latitude", "longitude"):
        actual = actual_location.get(coordinate)
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            raise InvalidOutputError("invalid_mcp_response")
        if float(actual) != location[coordinate]:
            raise InvalidOutputError("invalid_mcp_response")
    if dietary:
        refinements = tool_input.get("refinements")
        if not isinstance(refinements, Mapping):
            raise InvalidOutputError("invalid_mcp_response")
        actual_dietary = refinements.get("dietary")
        if not isinstance(actual_dietary, list) or sorted(actual_dietary) != list(
            dietary
        ):
            raise InvalidOutputError("invalid_mcp_response")


def _tool_payload(part: Mapping[str, Any]) -> dict[str, Any]:
    state = part.get("state")
    if not isinstance(state, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    raw = state.get("result", state.get("structured", state.get("output")))
    value = _decode_json_value(raw)
    if isinstance(value, Mapping) and isinstance(value.get("structuredContent"), Mapping):
        value = value["structuredContent"]
    if isinstance(value, Mapping) and isinstance(value.get("content"), list):
        texts = [
            item.get("text")
            for item in value["content"]
            if isinstance(item, Mapping) and item.get("type") == "text"
        ]
        for text in texts:
            decoded = _decode_json_value(text)
            if isinstance(decoded, Mapping):
                value = decoded
                break
    if not isinstance(value, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    return dict(value)


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return json.loads(value)


def _raise_mcp_error(payload: Mapping[str, Any]) -> None:
    errors = payload.get("errors")
    if not isinstance(errors, Mapping):
        return
    code = errors.get("code")
    mapping: dict[str, tuple[type[IntegrationError], str, bool]] = {
        "AUTHENTICATION_REQUIRED": (UnavailableError, "auth_required", False),
        "MISSING_LOCATION": (UnavailableError, "location_required", False),
        "SERVICE_UNAVAILABLE": (UnavailableError, "service_unavailable", True),
        "INVALID_QUERY": (InvalidOutputError, "invalid_query", False),
    }
    error_type, detail, retryable = mapping.get(
        str(code), (UnavailableError, "mcp_error", bool(errors.get("retryable")))
    )
    raise error_type(detail, retryable=retryable)


def _map_offers(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if payload.get("resultKind") != "ITEM":
        raise InvalidOutputError("invalid_mcp_response")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise InvalidOutputError("invalid_mcp_response")
    offers: list[dict[str, Any]] = []
    for raw in raw_results:
        if not isinstance(raw, Mapping):
            continue
        try:
            merchant = _required_mapping(raw, "merchant")
            delivery = _required_mapping(merchant, "deliveryMethod")
            price = raw.get("promotionalUnitPrice")
            if price is None:
                price = raw["unitPrice"]
            fee = delivery.get("promotionalFee")
            if fee is None:
                fee = delivery.get("fee")
            estimate = delivery.get("estimatedMinutes")
            eta = None
            if isinstance(estimate, Mapping):
                eta = _non_negative_int(estimate.get("max"))
                if eta is None:
                    eta = _non_negative_int(estimate.get("min"))
            offers.append(
                {
                    "product_id": _required_text(raw, "itemId"),
                    "name": _required_text(raw, "itemName"),
                    "unit_price_cents": _brl_to_cents(price),
                    "merchant_id": _required_text(merchant, "merchantId"),
                    "merchant_name": _required_text(merchant, "merchantName"),
                    "tags": [],
                    "delivery_fee_cents": None if fee is None else _brl_to_cents(fee),
                    "other_fees_cents": None,
                    "eta_minutes": eta,
                }
            )
        except (InvalidOutputError, KeyError, TypeError, ValueError):
            continue
    if raw_results and not offers:
        raise InvalidOutputError("invalid_mcp_response")
    return offers


def _required_mapping(source: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    return value


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidOutputError("invalid_mcp_response")
    return value


def _brl_to_cents(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise InvalidOutputError("invalid_mcp_response")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidOutputError("invalid_mcp_response") from exc
    if not amount.is_finite() or amount < 0:
        raise InvalidOutputError("invalid_mcp_response")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _tool_duration_ms(part: Mapping[str, Any]) -> int | None:
    state = part.get("state")
    if not isinstance(state, Mapping):
        return None
    time = state.get("time")
    if not isinstance(time, Mapping):
        return None
    start = time.get("start", time.get("created"))
    end = time.get("end", time.get("completed"))
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        return round(end - start)
    return None
