"""Implementação da porta dos agentes sobre OpenCode + MCP do iFood.

O módulo importa os tipos de ``backend.agents`` apenas ao materializar o
``RuntimeOutcome``. Assim, a branch de integrações não copia nem redefine o
contrato que pertence ao módulo de agentes.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from importlib import import_module
from math import isfinite
from time import monotonic
from typing import Any, Literal, Protocol

from .config import SAO_CARLOS_TEST_COORDINATES, OpenCodeSettings, SandboxLocation
from .errors import (
    IntegrationError,
    InvalidOutputError,
    QuotaError,
    RuntimeTimeoutError,
    UnavailableError,
)
from .opencode_client import OpenCodeClient, OpenCodeRunResult
from .search_quality import (
    CLOSED_TEST_TAG,
    SearchEvidenceStore,
    SearchIntent,
    normalized_text,
    select_matching_offers,
)

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

    async def create_session(
        self,
        *,
        title: str | None = None,
        allow_search: bool = True,
    ) -> str: ...

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

    async def abort_session(self, session_id: str) -> bool: ...


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


@dataclass(frozen=True, slots=True)
class _ResolvedLocation:
    coordinates: dict[str, float]
    source: Literal["context", "sandbox", "public_test"]


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
        evidence_store: SearchEvidenceStore | None = None,
        include_closed_for_testing: bool = False,
    ) -> None:
        self._settings = settings
        self._sandbox_location = sandbox_location
        self._client_factory = client_factory or (lambda: OpenCodeClient(settings))
        self._evidence = evidence_store or SearchEvidenceStore()
        self._include_closed_for_testing = include_closed_for_testing
        self._quota_until = 0.0

    def recommendation_warnings(
        self,
        session_id: str,
        merchant_id: str,
        product_ids: Sequence[str],
    ) -> list[str]:
        return self._evidence.recommendation_warnings(session_id, merchant_id, product_ids)

    def recommendation_details(
        self,
        session_id: str,
        merchant_id: str,
        product_ids: Sequence[str],
    ) -> dict[str, Any]:
        return self._evidence.recommendation_details(session_id, merchant_id, product_ids)

    def run(self, call: _RuntimeCallLike) -> Any:
        """Executa a chamada síncrona exigida por ``AgentRuntimePort``."""

        clients: list[Any] = []
        result = asyncio.run(self._execute(call, clients))
        ports = import_module("backend.agents.ports")
        usage = _sum_usage(getattr(client, "last_usage", None) for client in clients)
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
            usage=ports.Usage(**usage) if usage is not None else None,
        )

    async def _execute(self, call: _RuntimeCallLike, clients: list[Any] | None = None) -> _ExecutionResult:
        if monotonic() < self._quota_until:
            return _failure("quota", "quota_exceeded", retry_after_s=30)
        if not call.allowed_tools and call.max_tool_calls == 0:
            return await self._execute_reasoning(call, clients)
        if _LOGICAL_TOOL not in call.allowed_tools:
            return _failure("invalid_output", "tool_not_allowed")
        if call.max_tool_calls < 1:
            return _failure("invalid_output", "tool_call_limit")

        try:
            intent = SearchIntent.from_prompt(call.prompt)
        except InvalidOutputError:
            return _failure("invalid_output", "invalid_query")
        resolved_location = _resolve_location(call.context, self._sandbox_location)
        if resolved_location is None:
            return _failure("unavailable", "location_required")
        location = resolved_location.coordinates
        dietary = _read_dietary_filters(call.context)
        merchant_type, merchant_id = _read_scope(call.context)
        client = self._client_factory()
        if clients is not None:
            clients.append(client)
        started_at = monotonic()
        session_id = None
        try:
            tool_ids = await client.list_tool_ids()
            tool_id = _resolve_search_tool(tool_ids, self._settings.mcp_server_name)
            enabled_tools = {"*": False, **{item: item == tool_id for item in tool_ids}}
            session_id = await client.create_session(title=f"{call.agent_id}:{call.task_id}"[:120])
            response = await client.run_prompt(
                session_id,
                agent=self._settings.search_agent,
                system=call.system,
                prompt=_build_search_prompt(
                    call.prompt,
                    location,
                    dietary,
                    only_open=not self._include_closed_for_testing,
                    merchant_type=merchant_type,
                    merchant_id=merchant_id,
                ),
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
            only_open = not self._include_closed_for_testing
            _validate_tool_input(part, location=location, dietary=dietary, only_open=only_open,
                                 merchant_type=merchant_type, merchant_id=merchant_id)
            intent.validate_query(part["state"]["input"]["query"])
            offers, mismatches = select_matching_offers(
                _map_offers(
                    payload,
                    include_closed_for_testing=self._include_closed_for_testing,
                ),
                intent,
            )
            duration_ms = _tool_duration_ms(part)
            if duration_ms is None:
                duration_ms = max(0, round((monotonic() - started_at) * 1000))
            call_id = part.get("callID") or part.get("id")
            if not isinstance(call_id, str) or not call_id:
                raise InvalidOutputError("missing_call_id")
            self._evidence.record(
                call.session_id,
                offers,
                public_location=resolved_location.source == "public_test",
                customization=intent.customization_requested,
                only_open=only_open,
            )
            trace = _TraceData(
                call_id=call_id,
                tool_name=_LOGICAL_TOOL,
                provider="ifood_mcp",
                status="succeeded",
                duration_ms=duration_ms,
                summary=(
                    _trace_summary(len(offers), resolved_location.source)
                    + (
                        " Filtro oficial onlyOpen aplicado na consulta."
                        if only_open
                        else " Modo local de teste: restaurantes fechados podem ser exibidos, "
                        "sem disponibilidade para pedido."
                    )
                    + (
                        f" {mismatches} item(ns) sem correspondência textual descartado(s)."
                        if mismatches
                        else ""
                    )
                ),
            )
            return _ExecutionResult(
                ok=True,
                structured={"offers": offers},
                traces=(trace,),
                detail=(
                    "sandbox_location_used"
                    if resolved_location.source == "sandbox"
                    else "test_location_used"
                    if resolved_location.source == "public_test"
                    else None
                ),
            )
        except IntegrationError as exc:
            if session_id is not None and isinstance(exc, RuntimeTimeoutError):
                try:
                    await client.abort_session(session_id)
                except Exception:
                    pass
            retry_after = 30 if isinstance(exc, QuotaError) else None
            if retry_after is not None:
                self._quota_until = monotonic() + retry_after
            return _failure(exc.code, _safe_detail(exc), retry_after_s=retry_after)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return _failure("invalid_output", "invalid_mcp_response")
        finally:
            await client.aclose()

    async def _execute_reasoning(self, call: _RuntimeCallLike, clients: list[Any] | None = None) -> _ExecutionResult:
        """Raciocínio sem MCP: só a ferramenta interna de serialização do JSON."""

        client = self._client_factory()
        if clients is not None:
            clients.append(client)
        session_id = None
        try:
            session_id = await client.create_session(
                title=f"{call.agent_id}:{call.task_id}"[:120],
                allow_search=False,
            )
            response = await client.run_prompt(
                session_id,
                agent=self._settings.reasoning_agent,
                system=call.system,
                prompt=call.prompt,
                tools={"*": False, "StructuredOutput": True},
                output_schema=call.output_schema,
                timeout_seconds=call.timeout_s,
            )
            if not isinstance(response.structured_output, Mapping):
                raise InvalidOutputError("invalid_model_output", retryable=False)
            return _ExecutionResult(
                ok=True,
                structured=dict(response.structured_output),
                traces=(),
            )
        except IntegrationError as exc:
            if session_id is not None and isinstance(exc, RuntimeTimeoutError):
                try:
                    await client.abort_session(session_id)
                except Exception:
                    pass
            retry_after = 30 if isinstance(exc, QuotaError) else None
            if retry_after is not None:
                self._quota_until = monotonic() + retry_after
            return _failure(exc.code, _safe_detail(exc), retry_after_s=retry_after)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return _failure("invalid_output", "invalid_model_output")
        finally:
            await client.aclose()


def _sum_usage(items: Any) -> dict[str, Any] | None:
    """Consumo de todas as execuções da chamada (tokens e custo em US$ informados pelo OpenCode)."""
    found = [item for item in items if isinstance(item, Mapping)]
    if not found:
        return None
    keys = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    total: dict[str, Any] = {key: sum(int(item.get(key, 0)) for item in found) for key in keys}
    total["cost_usd"] = sum(float(item.get("cost_usd", 0.0)) for item in found)
    return total


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
        "invalid_model_output",
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
) -> _ResolvedLocation | None:
    raw = context.get("location")
    if isinstance(raw, Mapping):
        latitude = raw.get("latitude")
        longitude = raw.get("longitude")
        if _coordinate(latitude, -90, 90) and _coordinate(longitude, -180, 180):
            return _ResolvedLocation(
                {"latitude": float(latitude), "longitude": float(longitude)},
                "context",
            )
        return None  # Coordenadas explícitas inválidas não viram outra cidade silenciosamente.
    if fallback is not None:
        if (
            fallback.source == "public_test"
            and (fallback.latitude, fallback.longitude) == SAO_CARLOS_TEST_COORDINATES
            and isinstance(raw, str)
            and raw.strip()
            and normalized_text(raw).strip().replace(",", "")
            not in {"sao carlos", "sao carlos sp", "sao carlos sao paulo"}
        ):
            return None
        return _ResolvedLocation(
            {"latitude": fallback.latitude, "longitude": fallback.longitude},
            fallback.source,
        )
    return None


def _trace_summary(offer_count: int, location_source: str) -> str:
    summary = f"Busca MCP concluída com {offer_count} oferta(s)."
    if location_source == "sandbox":
        return f"{summary} Localização de sandbox utilizada."
    if location_source == "public_test":
        return f"{summary} Localização pública de teste utilizada; não é a localização do cliente."
    return summary


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


_MERCHANT_TYPES = {"RESTAURANT", "GROCERIES"}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _read_scope(context: Mapping[str, Any]) -> tuple[str, str | None]:
    """Vertical (padrão RESTAURANT) e loja opcional pedidos pelos agentes; valores fora da lista são ignorados."""
    kind = context.get("merchant_type")
    merchant = context.get("merchant_id")
    return (kind if kind in _MERCHANT_TYPES else "RESTAURANT",
            merchant if isinstance(merchant, str) and _UUID.match(merchant) else None)


def _build_search_prompt(
    agent_prompt: str,
    location: Mapping[str, float],
    dietary: Sequence[str],
    *,
    only_open: bool = True,
    merchant_type: str = "RESTAURANT",
    merchant_id: str | None = None,
) -> str:
    required_terms = sorted(SearchIntent.from_prompt(agent_prompt).terms)
    dietary_instruction = (
        f"Use refinements.itemRestrictions={json.dumps(list(dietary))}. "
        if dietary
        else "Não envie refinements.itemRestrictions. "
    )
    return (
        f"Uma chamada searchOffers: resultKind=ITEM, merchantType={merchant_type}, "
        "pageSize=20, refinements.sort=RELEVANCE. Use exatamente "
        + (f"refinements.merchantId={json.dumps(merchant_id)}. " if merchant_id else "")
        + 
        f"userLocation={json.dumps(dict(location), ensure_ascii=False)}. "
        f"{dietary_instruction}"
        f"Use refinements.onlyOpen={'true' if only_open else 'false'}. "
        "Preserve o prato na query, sem pessoas/orçamento; não troque por ingrediente ou sabor. "
        f"Termos obrigatórios: {json.dumps(required_terms)}. "
        "Sem outras tools, inferência de endereço ou personalização não confirmada. "
        "Após a ferramenta responda só OK. Pedido:\n"
        f"{agent_prompt}"
    )


def _completed_tool_part(
    raw_response: Mapping[str, Any], *, tool_id: str, max_tool_calls: int
) -> Mapping[str, Any]:
    parts = raw_response.get("parts")
    if not isinstance(parts, list):
        raise InvalidOutputError("invalid_mcp_response")
    tool_parts = [
        part for part in parts if isinstance(part, Mapping) and part.get("type") == "tool"
    ]
    if len(tool_parts) > max_tool_calls or any(
        (part.get("tool") or part.get("name")) != tool_id for part in tool_parts
    ):
        raise InvalidOutputError("invalid_mcp_response")
    matching = [part for part in tool_parts if (part.get("tool") or part.get("name")) == tool_id]
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
    only_open: bool | None = None,
    merchant_type: str = "RESTAURANT",
    merchant_id: str | None = None,
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
    if tool_input.get("resultKind") != "ITEM" or tool_input.get("merchantType", "RESTAURANT") != merchant_type:
        raise InvalidOutputError("invalid_mcp_response")
    if merchant_id is not None and (tool_input.get("refinements") or {}).get("merchantId") != merchant_id:
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
    if only_open is not None:
        refinements = tool_input.get("refinements")
        if (
            not isinstance(refinements, Mapping)
            or refinements.get("onlyOpen") is not only_open
        ):
            raise InvalidOutputError("invalid_mcp_response")
    if dietary:
        refinements = tool_input.get("refinements")
        if not isinstance(refinements, Mapping):
            raise InvalidOutputError("invalid_mcp_response")
        actual_dietary = refinements.get("itemRestrictions")
        if not isinstance(actual_dietary, list) or sorted(actual_dietary) != list(dietary):
            raise InvalidOutputError("invalid_mcp_response")
    else:
        refinements = tool_input.get("refinements")
        if isinstance(refinements, Mapping) and refinements.get("itemRestrictions"):
            raise InvalidOutputError("invalid_mcp_response")


def _tool_payload(part: Mapping[str, Any]) -> dict[str, Any]:
    state = part.get("state")
    if not isinstance(state, Mapping):
        raise InvalidOutputError("invalid_mcp_response")
    raw = state.get("result", state.get("structured", state.get("output")))
    value = _decode_json_value(raw)
    if isinstance(value, Mapping) and value.get("isError") is True:
        raise UnavailableError("mcp_error", retryable=False)
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
        if errors:
            raise UnavailableError("mcp_error", retryable=False)
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


def _map_offers(
    payload: Mapping[str, Any],
    *,
    include_closed_for_testing: bool = False,
) -> list[dict[str, Any]]:
    if payload.get("resultKind") != "ITEM":
        raise InvalidOutputError("invalid_mcp_response")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise InvalidOutputError("invalid_mcp_response")
    offers: list[dict[str, Any]] = []
    closed_filtered = 0
    for raw in raw_results:
        if not isinstance(raw, Mapping):
            continue
        try:
            merchant = _required_mapping(raw, "merchant")
            closed_for_testing = merchant.get("isOpen") is False
            if closed_for_testing and not include_closed_for_testing:
                closed_filtered += 1
                continue
            delivery = _required_mapping(merchant, "deliveryMethod")
            price = raw.get("promotionalUnitPrice")
            if price is None:
                price = raw["unitPrice"]
            effective_price_cents = _brl_to_cents(price)
            original_price_cents = _brl_to_cents(raw["unitPrice"])
            fee = delivery.get("promotionalFee")
            if fee is None:
                fee = delivery.get("fee")
            estimate = delivery.get("estimatedMinutes")
            eta = None
            eta_min = None
            if isinstance(estimate, Mapping):
                eta_min = _non_negative_int(estimate.get("min"))
                eta = _non_negative_int(estimate.get("max"))
                if eta is None:
                    eta = eta_min
                elif eta_min is not None and eta_min > eta:
                    eta_min = None
            distance_km = _optional_decimal(
                merchant.get("distanceKm", raw.get("distanceKm")),
                minimum=0,
            )
            merchant_rating = _optional_decimal(merchant.get("rating"), minimum=0, maximum=5)
            image_url = raw.get("imageUrl")
            if not isinstance(image_url, str) or not image_url.startswith(("http://", "https://")):
                image_url = None
            offers.append(
                {
                    "product_id": _required_text(raw, "itemId"),
                    "name": _required_text(raw, "itemName"),
                    "unit_price_cents": effective_price_cents,
                    "original_unit_price_cents": (
                        original_price_cents
                        if original_price_cents > effective_price_cents
                        else None
                    ),
                    "image_url": image_url,
                    "merchant_id": _required_text(merchant, "merchantId"),
                    "merchant_name": _required_text(merchant, "merchantName"),
                    "tags": [CLOSED_TEST_TAG] if closed_for_testing else [],
                    "delivery_fee_cents": None if fee is None else _brl_to_cents(fee),
                    "other_fees_cents": None,
                    "eta_minutes": eta,
                    "eta_min_minutes": eta_min,
                    "distance_km": distance_km,
                    "merchant_rating": merchant_rating,
                    "_merchant_is_open": (
                        merchant["isOpen"]
                        if isinstance(merchant.get("isOpen"), bool)
                        else None
                    ),
                    **(
                        {"is_open": merchant["isOpen"]}
                        if isinstance(merchant.get("isOpen"), bool) and not closed_for_testing
                        else {}
                    ),
                }
            )
        except (InvalidOutputError, KeyError, TypeError, ValueError):
            continue
    if raw_results and not offers and not closed_filtered:
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


def _optional_decimal(
    value: Any,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed) or parsed < minimum or (
        maximum is not None and parsed > maximum
    ):
        return None
    return parsed


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
