"""DTOs fechados do contrato público definido na seção 15 do PROMPT.md."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True, populate_by_name=True)


class Mode(str, Enum):
    REAL = "real"
    DEMO = "demo"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    WAITING_CUSTOMER = "waiting_customer"
    CLOSED = "closed"
    ERROR = "error"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    ERROR = "error"


class Visibility(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    BOTH = "both"


class ActorKind(str, Enum):
    SYSTEM = "system"
    AGENT = "agent"
    CUSTOMER = "customer"
    TOOL = "tool"


class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    CHAT_MESSAGE = "chat_message"
    AGENT_STATUS = "agent_status"
    AGENT_MESSAGE = "agent_message"
    TOOL_ACTIVITY = "tool_activity"
    KNOWLEDGE_RETRIEVED = "knowledge_retrieved"
    MEMORY_CHANGED = "memory_changed"
    PATTERN_IDENTIFIED = "pattern_identified"
    DISCOUNT_PROPOSED = "discount_proposed"
    CONFLICT_DETECTED = "conflict_detected"
    DECISION_MADE = "decision_made"
    RECOMMENDATIONS_READY = "recommendations_ready"
    CART_CHANGED = "cart_changed"
    ORDER_STATUS_CHANGED = "order_status_changed"
    ERROR = "error"
    SESSION_CLOSED = "session_closed"


class Actor(StrictModel):
    kind: ActorKind
    id: NonEmptyStr


class AgentDefinition(StrictModel):
    agent_id: NonEmptyStr
    name: NonEmptyStr
    role: NonEmptyStr
    description: NonEmptyStr
    capabilities: list[NonEmptyStr]
    enabled: bool


class AgentRuntime(StrictModel):
    agent_id: NonEmptyStr
    status: AgentStatus
    task_id: NonEmptyStr | None
    summary: NonEmptyStr | None


class ChatMessage(StrictModel):
    message_id: NonEmptyStr
    role: Literal["customer", "assistant"]
    input_mode: Literal["text", "audio"]
    text: NonEmptyStr
    created_at: AwareDatetime

    @model_validator(mode="after")
    def assistant_is_always_text(self) -> ChatMessage:
        if self.role == "assistant" and self.input_mode != "text":
            raise ValueError("respostas do assistente precisam usar input_mode text")
        return self


class CartItem(StrictModel):
    product_id: NonEmptyStr
    name: NonEmptyStr
    quantity: PositiveInt
    unit_price_cents: NonNegativeInt
    original_unit_price_cents: NonNegativeInt | None = None
    image_url: NonEmptyStr | None = None


class Recommendation(StrictModel):
    recommendation_id: NonEmptyStr
    merchant_id: NonEmptyStr
    merchant_name: NonEmptyStr
    items: list[CartItem]
    currency: Literal["BRL"]
    subtotal_cents: NonNegativeInt | None
    delivery_fee_cents: NonNegativeInt | None
    other_fees_cents: NonNegativeInt | None
    discount_cents: NonNegativeInt
    total_cents: NonNegativeInt | None
    eta_minutes: NonNegativeInt | None
    eta_min_minutes: NonNegativeInt | None = None
    distance_km: Annotated[float, Field(ge=0)] | None = None
    merchant_rating: Annotated[float, Field(ge=0, le=5)] | None = None
    is_open: bool | None = None
    reasons: list[NonEmptyStr]
    warnings: list[NonEmptyStr]
    data_origin: Literal["ifood_mcp", "demo"]

    @model_validator(mode="after")
    def validate_total_when_complete(self) -> Recommendation:
        components = (
            self.subtotal_cents,
            self.delivery_fee_cents,
            self.other_fees_cents,
        )
        if all(component is not None for component in components):
            expected = sum(component for component in components if component is not None)
            expected -= self.discount_cents
            if expected < 0:
                raise ValueError("discount_cents não pode tornar o total negativo")
            if self.total_cents is not None and self.total_cents != expected:
                raise ValueError("total_cents não corresponde aos componentes")
        elif self.total_cents is not None:
            raise ValueError("total_cents exige todos os componentes conhecidos")
        if (
            self.eta_min_minutes is not None
            and self.eta_minutes is not None
            and self.eta_min_minutes > self.eta_minutes
        ):
            raise ValueError("eta_min_minutes não pode exceder eta_minutes")
        for item in self.items:
            if (
                item.original_unit_price_cents is not None
                and item.original_unit_price_cents < item.unit_price_cents
            ):
                raise ValueError("preço original não pode ser menor que o preço atual")
        return self


class Cart(StrictModel):
    cart_id: NonEmptyStr | None
    status: Literal["empty", "draft", "ready", "submitted", "error"]
    items: list[CartItem]
    currency: Literal["BRL"]
    total_cents: NonNegativeInt | None
    data_origin: Literal["ifood_mcp", "demo"]


class SessionStartedPayload(StrictModel):
    client_alias: NonEmptyStr


class ChatMessagePayload(StrictModel):
    message: ChatMessage


class AgentStatusPayload(StrictModel):
    agent_id: NonEmptyStr
    status: AgentStatus
    task_id: NonEmptyStr | None
    summary: NonEmptyStr | None


class AgentMessagePayload(StrictModel):
    message_id: NonEmptyStr
    task_id: NonEmptyStr
    channel: Literal["request", "proposal", "review", "resolution"]
    summary: NonEmptyStr


class ToolActivityPayload(StrictModel):
    call_id: NonEmptyStr
    tool_name: NonEmptyStr
    provider: Literal["ifood_mcp", "internal", "demo"]
    status: Literal["started", "succeeded", "failed"]
    duration_ms: NonNegativeInt | None
    summary: NonEmptyStr


class KnowledgeSource(StrictModel):
    document_id: NonEmptyStr
    title: NonEmptyStr


class KnowledgeRetrievedPayload(StrictModel):
    query_id: NonEmptyStr
    topics: list[NonEmptyStr]
    sources: list[KnowledgeSource]
    count: NonNegativeInt


class MemoryChangedPayload(StrictModel):
    scope: Literal["session", "customer", "company"]
    keys: list[NonEmptyStr]
    summary: NonEmptyStr


class PatternIdentifiedPayload(StrictModel):
    pattern_id: NonEmptyStr
    description: NonEmptyStr
    basis: Literal["historical_orders", "stated_preference", "demo"]
    evidence_count: NonNegativeInt
    confidence: Literal["low", "medium", "high"]


class DiscountProposedPayload(StrictModel):
    proposal_id: NonEmptyStr
    recommendation_id: NonEmptyStr
    discount_type: Literal["percent", "fixed"]
    discount_bps: NonNegativeInt | None
    discount_cents: NonNegativeInt | None
    estimated_profit_delta_cents: int | None
    status: Literal["suggested", "approved", "rejected"]
    requires_approval: bool
    reason: NonEmptyStr


class ConflictDetectedPayload(StrictModel):
    conflict_id: NonEmptyStr
    agent_ids: list[NonEmptyStr]
    description: NonEmptyStr
    status: Literal["open", "resolved"]


class DecisionMadePayload(StrictModel):
    decision_id: NonEmptyStr
    recommendation_id: NonEmptyStr | None
    summary: NonEmptyStr
    reasons: list[NonEmptyStr]
    limitations: list[NonEmptyStr]


class RecommendationsReadyPayload(StrictModel):
    recommendations: list[Recommendation]


class CartChangedPayload(StrictModel):
    cart: Cart


class OrderStatusChangedPayload(StrictModel):
    order_id: NonEmptyStr | None
    status: Literal["not_submitted", "submitted", "payment_pending", "confirmed", "failed"]
    summary: NonEmptyStr


class EventErrorPayload(StrictModel):
    code: NonEmptyStr
    message: NonEmptyStr
    retryable: bool


class SessionClosedPayload(StrictModel):
    outcome: Literal["order_submitted", "abandoned", "closed"]
    summary: NonEmptyStr


PAYLOAD_MODELS: dict[str, type[StrictModel]] = {
    EventType.SESSION_STARTED.value: SessionStartedPayload,
    EventType.CHAT_MESSAGE.value: ChatMessagePayload,
    EventType.AGENT_STATUS.value: AgentStatusPayload,
    EventType.AGENT_MESSAGE.value: AgentMessagePayload,
    EventType.TOOL_ACTIVITY.value: ToolActivityPayload,
    EventType.KNOWLEDGE_RETRIEVED.value: KnowledgeRetrievedPayload,
    EventType.MEMORY_CHANGED.value: MemoryChangedPayload,
    EventType.PATTERN_IDENTIFIED.value: PatternIdentifiedPayload,
    EventType.DISCOUNT_PROPOSED.value: DiscountProposedPayload,
    EventType.CONFLICT_DETECTED.value: ConflictDetectedPayload,
    EventType.DECISION_MADE.value: DecisionMadePayload,
    EventType.RECOMMENDATIONS_READY.value: RecommendationsReadyPayload,
    EventType.CART_CHANGED.value: CartChangedPayload,
    EventType.ORDER_STATUS_CHANGED.value: OrderStatusChangedPayload,
    EventType.ERROR.value: EventErrorPayload,
    EventType.SESSION_CLOSED.value: SessionClosedPayload,
}

EventPayload = (
    SessionStartedPayload
    | ChatMessagePayload
    | AgentStatusPayload
    | AgentMessagePayload
    | ToolActivityPayload
    | KnowledgeRetrievedPayload
    | MemoryChangedPayload
    | PatternIdentifiedPayload
    | DiscountProposedPayload
    | ConflictDetectedPayload
    | DecisionMadePayload
    | RecommendationsReadyPayload
    | CartChangedPayload
    | OrderStatusChangedPayload
    | EventErrorPayload
    | SessionClosedPayload
)


class OfficeEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: NonEmptyStr
    seq: Annotated[int, Field(ge=1)]
    occurred_at: AwareDatetime
    tenant_id: NonEmptyStr
    session_id: NonEmptyStr
    type: EventType
    actor: Actor
    recipient: Actor | None
    visibility: Visibility
    mode: Mode
    payload: EventPayload

    @model_validator(mode="after")
    def validate_payload_and_actors(self) -> OfficeEvent:
        event_type = self.type.value if isinstance(self.type, EventType) else self.type
        payload_model = PAYLOAD_MODELS[event_type]
        serialized_payload = self.payload.model_dump(mode="json")
        validated = payload_model.model_validate(serialized_payload)
        self.payload = validated
        if self.type == EventType.AGENT_MESSAGE.value:
            if self.actor.kind != ActorKind.AGENT.value:
                raise ValueError("agent_message exige actor.kind agent")
            if self.recipient is None or self.recipient.kind != ActorKind.AGENT.value:
                raise ValueError("agent_message exige recipient.kind agent")
        if self.type == EventType.CHAT_MESSAGE.value:
            role = serialized_payload["message"]["role"]
            expected_kind = "customer" if role == "customer" else "agent"
            if self.actor.kind != expected_kind:
                raise ValueError("ator incompatível com o papel da mensagem")
        return self


class InitialContext(StrictModel):
    name: NonEmptyStr | None
    age: Annotated[int, Field(strict=True, ge=0, le=130)] | None
    location: NonEmptyStr | None
    preferences: list[NonEmptyStr]
    restrictions: list[NonEmptyStr]


class SessionCreateRequest(StrictModel):
    client_id: NonEmptyStr | None
    initial_context: InitialContext | None = None


class SessionCreateResponse(StrictModel):
    schema_version: Literal[1] = 1
    session_id: NonEmptyStr
    client_alias: NonEmptyStr
    mode: Mode
    status: SessionStatus
    created_at: AwareDatetime


class TranscriptionResponse(StrictModel):
    schema_version: Literal[1] = 1
    transcription_id: NonEmptyStr
    text: NonEmptyStr
    language: NonEmptyStr
    requires_confirmation: bool


class ChatMessageRequest(StrictModel):
    session_id: NonEmptyStr
    client_message_id: NonEmptyStr
    text: NonEmptyStr
    input_mode: Literal["text", "audio"]
    transcription_id: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_transcription_reference(self) -> ChatMessageRequest:
        if self.input_mode == "text" and self.transcription_id is not None:
            raise ValueError("transcription_id precisa ser null para texto")
        if self.input_mode == "audio" and self.transcription_id is None:
            raise ValueError("transcription_id é obrigatório para áudio")
        return self


class ChatAcceptedResponse(StrictModel):
    schema_version: Literal[1] = 1
    session_id: NonEmptyStr
    client_message_id: NonEmptyStr
    status: Literal["accepted"] = "accepted"


class AgentCatalogResponse(StrictModel):
    schema_version: Literal[1] = 1
    agents: list[AgentDefinition]


class SessionSummary(StrictModel):
    session_id: NonEmptyStr
    client_alias: NonEmptyStr
    status: SessionStatus
    mode: Mode
    created_at: AwareDatetime
    updated_at: AwareDatetime


class SessionSnapshotResponse(StrictModel):
    schema_version: Literal[1] = 1
    session: SessionSummary
    last_seq: NonNegativeInt
    agents: list[AgentRuntime]
    messages: list[ChatMessage]
    recommendations: list[Recommendation]
    cart: Cart | None


class HistoryResponse(StrictModel):
    schema_version: Literal[1] = 1
    session_id: NonEmptyStr
    events: list[OfficeEvent]
    last_seq: NonNegativeInt
    has_more: bool


class OverviewWindow(StrictModel):
    from_: AwareDatetime = Field(alias="from", serialization_alias="from")
    to: AwareDatetime


class OverviewMetrics(StrictModel):
    sessions_started: NonNegativeInt
    messages_received: NonNegativeInt
    recommendations_made: NonNegativeInt
    orders_submitted: NonNegativeInt
    orders_confirmed: NonNegativeInt
    conversion_rate: Annotated[float, Field(ge=0, le=1)] | None
    average_response_ms: NonNegativeInt | None
    estimated_ai_cost_cents: NonNegativeInt | None
    revenue_cents: NonNegativeInt | None
    estimated_profit_cents: int | None


class RecentSession(StrictModel):
    session_id: NonEmptyStr
    client_alias: NonEmptyStr
    status: SessionStatus
    updated_at: AwareDatetime
    last_seq: NonNegativeInt


class AdminOverviewResponse(StrictModel):
    schema_version: Literal[1] = 1
    mode: Mode
    window: OverviewWindow
    metrics: OverviewMetrics
    recent_sessions: list[RecentSession]


class AiUsageClient(StrictModel):
    """Custo de IA e vendas aceitas de um cliente. Custo em US$ informado pelo provedor (micro-dólares);
    em R$, convertido pelo câmbio configurado. Lucro usa a margem suposta configurada (DEMO)."""

    client_label: NonEmptyStr
    sessions: NonNegativeInt
    fictitious_sessions: NonNegativeInt  # histórico FICTÍCIO da demonstração incluído nos números
    ai_calls: NonNegativeInt
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cache_tokens: NonNegativeInt
    ai_cost_usd_micros: NonNegativeInt
    ai_cost_cents: NonNegativeInt
    sales: NonNegativeInt
    sales_cents: NonNegativeInt
    ai_cost_share_bps: NonNegativeInt | None
    estimated_profit_cents: int | None


class AiUsageTotals(StrictModel):
    sessions: NonNegativeInt
    fictitious_sessions: NonNegativeInt
    ai_calls: NonNegativeInt
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cache_tokens: NonNegativeInt
    ai_cost_usd_micros: NonNegativeInt
    ai_cost_cents: NonNegativeInt
    sales: NonNegativeInt
    sales_cents: NonNegativeInt
    ai_cost_share_bps: NonNegativeInt | None
    estimated_profit_cents: int | None


class AiUsageResponse(StrictModel):
    schema_version: Literal[1] = 1
    usd_brl_rate: Annotated[float, Field(gt=0)]
    assumed_margin_bps: Annotated[int, Field(ge=0, le=10000)]
    clients: list[AiUsageClient]
    totals: AiUsageTotals


class SubmitOrderRequest(StrictModel):
    session_id: NonEmptyStr
    recommendation_id: NonEmptyStr
    client_action_id: NonEmptyStr
    confirmed: Literal[True]


class OrderAcceptedResponse(StrictModel):
    schema_version: Literal[1] = 1
    session_id: NonEmptyStr
    client_action_id: NonEmptyStr
    status: Literal["accepted"] = "accepted"


class HTTPErrorBody(StrictModel):
    code: NonEmptyStr
    message: NonEmptyStr
    retryable: bool
    details: list[str]


class HTTPErrorResponse(StrictModel):
    schema_version: Literal[1] = 1
    request_id: NonEmptyStr
    error: HTTPErrorBody
