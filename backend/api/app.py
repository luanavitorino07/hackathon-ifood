"""Aplicação FastAPI v1, composta por dependências injetáveis."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.integrations.errors import IntegrationError
from backend.integrations.transcription import TranscriptionProvider

from .errors import APIError
from .models import (
    AdminOverviewResponse,
    AgentCatalogResponse,
    ChatAcceptedResponse,
    ChatMessageRequest,
    EventType,
    HistoryResponse,
    HTTPErrorBody,
    HTTPErrorResponse,
    Mode,
    OrderAcceptedResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionSnapshotResponse,
    SubmitOrderRequest,
    TranscriptionResponse,
)
from .services import (
    AgentCatalogProvider,
    DemoCustomerIdentityResolver,
    EmptyAgentCatalog,
    IdentityResolver,
    MessageDispatch,
    MessageDispatcher,
    OrderDispatcher,
    RequestIdentity,
)
from .sse import format_keepalive, format_office_event
from .state import InMemoryBackendState

MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-wav",
}


def create_app(
    *,
    state: InMemoryBackendState | None = None,
    identity_resolver: IdentityResolver | None = None,
    message_dispatcher: MessageDispatcher | None = None,
    order_dispatcher: OrderDispatcher | None = None,
    agent_catalog: AgentCatalogProvider | None = None,
    transcription_provider: TranscriptionProvider | None = None,
) -> FastAPI:
    common_error_responses = {
        status: {"model": HTTPErrorResponse}
        for status in (400, 401, 403, 404, 409, 422, 429, 503)
    }
    app = FastAPI(
        title="Escritório Virtual Multiagente",
        version="1",
        responses=common_error_responses,
    )
    app.state.backend_state = state or InMemoryBackendState()
    app.state.identity_resolver = identity_resolver or DemoCustomerIdentityResolver()
    app.state.message_dispatcher = message_dispatcher
    app.state.order_dispatcher = order_dispatcher
    app.state.agent_catalog = agent_catalog or EmptyAgentCatalog()
    app.state.transcription_provider = transcription_provider

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            ".".join(str(part) for part in error["loc"]) + ": " + error["msg"]
            for error in exc.errors()
        ]
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="A solicitação contém campos inválidos.",
            retryable=False,
            details=details,
        )

    @app.exception_handler(IntegrationError)
    async def integration_error_handler(
        _: Request, exc: IntegrationError
    ) -> JSONResponse:
        status_code = 429 if exc.code == "quota" else 503
        return _error_response(
            status_code=status_code,
            code=exc.code.upper(),
            message=str(exc),
            retryable=exc.retryable,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        codes = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }
        return _error_response(
            status_code=exc.status_code,
            code=codes.get(exc.status_code, "HTTP_ERROR"),
            message="A solicitação HTTP não pôde ser atendida.",
            retryable=False,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="Ocorreu uma falha interna no processamento.",
            retryable=False,
        )

    @app.post(
        "/api/v1/sessions",
        response_model=SessionCreateResponse,
        status_code=201,
    )
    async def create_session(
        payload: SessionCreateRequest, request: Request
    ) -> SessionCreateResponse:
        identity = await _identity(request)
        return await _state(request).create_session(
            identity=identity,
            client_id=payload.client_id,
            mode=Mode.DEMO,
        )

    @app.post(
        "/api/v1/audio/transcriptions",
        response_model=TranscriptionResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["audio"],
                            "properties": {
                                "audio": {"type": "string", "format": "binary"},
                                "language": {
                                    "type": "string",
                                    "enum": ["pt-BR"],
                                    "default": "pt-BR",
                                },
                            },
                        }
                    }
                },
            }
        },
    )
    async def transcribe_audio(request: Request) -> TranscriptionResponse:
        provider: TranscriptionProvider | None = request.app.state.transcription_provider
        if provider is None:
            raise APIError(
                503,
                "STT_UNAVAILABLE",
                "A transcrição de áudio não está configurada.",
                retryable=False,
            )
        form = await request.form()
        extra_fields = set(form.keys()) - {"audio", "language"}
        if extra_fields:
            raise APIError(
                422,
                "VALIDATION_ERROR",
                "O formulário de áudio contém campos não permitidos.",
                details=sorted(extra_fields),
            )
        audio = form.get("audio")
        language = form.get("language", "pt-BR")
        if not isinstance(audio, UploadFile) or language != "pt-BR":
            raise APIError(
                422,
                "VALIDATION_ERROR",
                "Envie um arquivo de áudio com language pt-BR.",
            )
        if audio.content_type not in ALLOWED_AUDIO_TYPES:
            raise APIError(422, "UNSUPPORTED_AUDIO", "Formato de áudio não suportado.")
        content = await audio.read(MAX_AUDIO_BYTES + 1)
        if not content or len(content) > MAX_AUDIO_BYTES:
            raise APIError(
                422,
                "INVALID_AUDIO_SIZE",
                "O áudio está vazio ou excede o limite permitido.",
            )
        result = await provider.transcribe(
            content,
            content_type=audio.content_type,
            language="pt-BR",
        )
        return TranscriptionResponse(
            transcription_id=f"tr_{uuid4().hex}",
            text=result.text,
            language=result.language,
            requires_confirmation=result.requires_confirmation,
        )

    @app.post(
        "/api/v1/chat/messages",
        response_model=ChatAcceptedResponse,
        status_code=202,
    )
    async def send_message(
        payload: ChatMessageRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> ChatAcceptedResponse:
        identity = await _identity(request)
        accepted = await _state(request).accept_message(payload, identity)
        client_id = await _state(request).session_client_id(payload.session_id, identity)
        background_tasks.add_task(
            _dispatch_message,
            request.app,
            MessageDispatch(
                tenant_id=identity.tenant_id,
                client_id=client_id,
                request=payload,
            ),
            identity,
        )
        return accepted

    @app.get("/api/v1/agents", response_model=AgentCatalogResponse)
    async def list_agents(request: Request) -> AgentCatalogResponse:
        identity = await _identity(request)
        if identity.role != "admin":
            raise APIError(403, "FORBIDDEN", "Credencial de gestor necessária.")
        agents = await request.app.state.agent_catalog.list_agents()
        return AgentCatalogResponse(agents=agents)

    @app.get(
        "/api/v1/sessions/{session_id}/snapshot",
        response_model=SessionSnapshotResponse,
    )
    async def session_snapshot(
        session_id: str, request: Request
    ) -> SessionSnapshotResponse:
        return await _state(request).snapshot(session_id, await _identity(request))

    @app.get(
        "/api/v1/sessions/{session_id}/history",
        response_model=HistoryResponse,
    )
    async def session_history(
        session_id: str,
        request: Request,
        after_seq: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=200),
    ) -> HistoryResponse:
        return await _state(request).history(
            session_id,
            await _identity(request),
            after_seq=after_seq,
            limit=limit,
        )

    @app.get("/api/v1/admin/overview", response_model=AdminOverviewResponse)
    async def admin_overview(request: Request) -> AdminOverviewResponse:
        return await _state(request).overview(await _identity(request))

    @app.post(
        "/api/v1/orders/submit",
        response_model=OrderAcceptedResponse,
        status_code=202,
    )
    async def submit_order(
        payload: SubmitOrderRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> OrderAcceptedResponse:
        identity = await _identity(request)
        await _state(request).session_client_id(payload.session_id, identity)
        dispatcher: OrderDispatcher | None = request.app.state.order_dispatcher
        if dispatcher is None:
            raise APIError(
                503,
                "ORDER_SUBMISSION_UNAVAILABLE",
                "A submissão de pedidos ainda não está habilitada.",
                retryable=False,
            )
        background_tasks.add_task(dispatcher.dispatch, payload, identity)
        return OrderAcceptedResponse(
            session_id=payload.session_id,
            client_action_id=payload.client_action_id,
        )

    @app.get(
        "/api/v1/sessions/{session_id}/events",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Fluxo SSE de OfficeEvent",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    async def session_events(
        session_id: str,
        request: Request,
        after_seq: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        identity = await _identity(request)
        await _state(request).session_client_id(session_id, identity)
        header_seq = _last_event_seq(request.headers.get("last-event-id"))
        cursor = max(after_seq, header_seq)

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            while not await request.is_disconnected():
                events = await _state(request).wait_for_events(
                    session_id,
                    identity,
                    after_seq=cursor,
                    timeout_seconds=15,
                )
                if not events:
                    yield format_keepalive()
                    continue
                for event in events:
                    cursor = event.seq
                    yield format_office_event(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


async def _dispatch_message(
    app: FastAPI,
    message: MessageDispatch,
    identity: RequestIdentity,
) -> None:
    dispatcher: MessageDispatcher | None = app.state.message_dispatcher
    if dispatcher is None:
        await app.state.backend_state.publish_event(
            session_id=message.request.session_id,
            identity=identity,
            event_type=EventType.ERROR,
            actor={"kind": "system", "id": "api"},
            recipient=None,
            visibility="both",
            payload={
                "code": "RUNTIME_UNAVAILABLE",
                "message": "O runtime de agentes ainda não está conectado.",
                "retryable": True,
            },
        )
        return
    try:
        await dispatcher.dispatch(message)
    except IntegrationError as exc:
        await app.state.backend_state.publish_event(
            session_id=message.request.session_id,
            identity=identity,
            event_type=EventType.ERROR,
            actor={"kind": "system", "id": "integration"},
            recipient=None,
            visibility="both",
            payload={
                "code": exc.code.upper(),
                "message": str(exc),
                "retryable": exc.retryable,
            },
        )
    # Esta é a fronteira de uma tarefa em background: falhas desconhecidas são
    # convertidas em evento público genérico, sem expor stack trace ou segredo.
    except Exception:  # noqa: BLE001
        await app.state.backend_state.publish_event(
            session_id=message.request.session_id,
            identity=identity,
            event_type=EventType.ERROR,
            actor={"kind": "system", "id": "orchestrator"},
            recipient=None,
            visibility="both",
            payload={
                "code": "INTERNAL_ERROR",
                "message": "Não foi possível processar a mensagem.",
                "retryable": False,
            },
        )


def _state(request: Request) -> InMemoryBackendState:
    return request.app.state.backend_state


async def _identity(request: Request) -> RequestIdentity:
    return await request.app.state.identity_resolver.resolve(request)


def _last_event_seq(value: str | None) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except ValueError as exc:
        raise APIError(400, "INVALID_LAST_EVENT_ID", "Last-Event-ID inválido.") from exc
    if parsed < 0:
        raise APIError(400, "INVALID_LAST_EVENT_ID", "Last-Event-ID inválido.")
    return parsed


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    details: list[str] | None = None,
) -> JSONResponse:
    payload = HTTPErrorResponse(
        request_id=f"req_{uuid4().hex}",
        error=HTTPErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            details=details or [],
        ),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
