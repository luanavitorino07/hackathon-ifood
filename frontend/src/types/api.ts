// Gerado dos DTOs Pydantic do backend; dinheiro em centavos.
export type ActorKind = "system" | "agent" | "customer" | "tool";
export type Actor = { kind: ActorKind; id: string };
export type AgentDefinition = {
  agent_id: string;
  name: string;
  role: string;
  description: string;
  capabilities: string[];
  enabled: boolean;
};
export type AgentStatus = "idle" | "running" | "waiting" | "done" | "error";
export type AgentRuntime = {
  agent_id: string;
  status: AgentStatus;
  task_id: string | null;
  summary: string | null;
};
export type ChatMessage = {
  message_id: string;
  role: "customer" | "assistant";
  input_mode: "text" | "audio";
  text: string;
  created_at: string;
};
export type CartItem = {
  product_id: string;
  name: string;
  quantity: number;
  unit_price_cents: number;
};
export type Recommendation = {
  recommendation_id: string;
  merchant_id: string;
  merchant_name: string;
  items: CartItem[];
  currency: "BRL";
  subtotal_cents: number | null;
  delivery_fee_cents: number | null;
  other_fees_cents: number | null;
  discount_cents: number;
  total_cents: number | null;
  eta_minutes: number | null;
  reasons: string[];
  warnings: string[];
  data_origin: "ifood_mcp" | "demo";
};
export type Cart = {
  cart_id: string | null;
  status: "empty" | "draft" | "ready" | "submitted" | "error";
  items: CartItem[];
  currency: "BRL";
  total_cents: number | null;
  data_origin: "ifood_mcp" | "demo";
};
export type SessionStartedPayload = { client_alias: string };
export type ChatMessagePayload = { message: ChatMessage };
export type AgentStatusPayload = {
  agent_id: string;
  status: AgentStatus;
  task_id: string | null;
  summary: string | null;
};
export type AgentMessagePayload = {
  message_id: string;
  task_id: string;
  channel: "request" | "proposal" | "review" | "resolution";
  summary: string;
};
export type ToolActivityPayload = {
  call_id: string;
  tool_name: string;
  provider: "ifood_mcp" | "internal" | "demo";
  status: "started" | "succeeded" | "failed";
  duration_ms: number | null;
  summary: string;
};
export type KnowledgeSource = { document_id: string; title: string };
export type KnowledgeRetrievedPayload = {
  query_id: string;
  topics: string[];
  sources: KnowledgeSource[];
  count: number;
};
export type MemoryChangedPayload = {
  scope: "session" | "customer" | "company";
  keys: string[];
  summary: string;
};
export type PatternIdentifiedPayload = {
  pattern_id: string;
  description: string;
  basis: "historical_orders" | "stated_preference" | "demo";
  evidence_count: number;
  confidence: "low" | "medium" | "high";
};
export type DiscountProposedPayload = {
  proposal_id: string;
  recommendation_id: string;
  discount_type: "percent" | "fixed";
  discount_bps: number | null;
  discount_cents: number | null;
  estimated_profit_delta_cents: number | null;
  status: "suggested" | "approved" | "rejected";
  requires_approval: boolean;
  reason: string;
};
export type ConflictDetectedPayload = {
  conflict_id: string;
  agent_ids: string[];
  description: string;
  status: "open" | "resolved";
};
export type DecisionMadePayload = {
  decision_id: string;
  recommendation_id: string | null;
  summary: string;
  reasons: string[];
  limitations: string[];
};
export type RecommendationsReadyPayload = { recommendations: Recommendation[] };
export type CartChangedPayload = { cart: Cart };
export type OrderStatusChangedPayload = {
  order_id: string | null;
  status:
    "not_submitted" | "submitted" | "payment_pending" | "confirmed" | "failed";
  summary: string;
};
export type EventErrorPayload = {
  code: string;
  message: string;
  retryable: boolean;
};
export type SessionClosedPayload = {
  outcome: "order_submitted" | "abandoned" | "closed";
  summary: string;
};
export type EventType =
  | "session_started"
  | "chat_message"
  | "agent_status"
  | "agent_message"
  | "tool_activity"
  | "knowledge_retrieved"
  | "memory_changed"
  | "pattern_identified"
  | "discount_proposed"
  | "conflict_detected"
  | "decision_made"
  | "recommendations_ready"
  | "cart_changed"
  | "order_status_changed"
  | "error"
  | "session_closed";
export type Mode = "real" | "demo";
export type Visibility = "admin" | "customer" | "both";
export type InitialContext = {
  name: string | null;
  age: number | null;
  location: string | null;
  preferences: string[];
  restrictions: string[];
};
export type SessionCreateRequest = {
  client_id: string | null;
  initial_context?: InitialContext | null;
};
export type SessionStatus = "active" | "waiting_customer" | "closed" | "error";
export type SessionCreateResponse = {
  schema_version: 1;
  session_id: string;
  client_alias: string;
  mode: Mode;
  status: SessionStatus;
  created_at: string;
};
export type TranscriptionResponse = {
  schema_version: 1;
  transcription_id: string;
  text: string;
  language: string;
  requires_confirmation: boolean;
};
export type ChatMessageRequest = {
  session_id: string;
  client_message_id: string;
  text: string;
  input_mode: "text" | "audio";
  transcription_id: string | null;
};
export type ChatAcceptedResponse = {
  schema_version: 1;
  session_id: string;
  client_message_id: string;
  status: "accepted";
};
export type AgentCatalogResponse = {
  schema_version: 1;
  agents: AgentDefinition[];
};
export type SessionSummary = {
  session_id: string;
  client_alias: string;
  status: SessionStatus;
  mode: Mode;
  created_at: string;
  updated_at: string;
};
export type SessionSnapshotResponse = {
  schema_version: 1;
  session: SessionSummary;
  last_seq: number;
  agents: AgentRuntime[];
  messages: ChatMessage[];
  recommendations: Recommendation[];
  cart: Cart | null;
};
export type HistoryResponse = {
  schema_version: 1;
  session_id: string;
  events: OfficeEvent[];
  last_seq: number;
  has_more: boolean;
};
export type OverviewWindow = { from: string; to: string };
export type OverviewMetrics = {
  sessions_started: number;
  messages_received: number;
  recommendations_made: number;
  orders_submitted: number;
  orders_confirmed: number;
  conversion_rate: number | null;
  average_response_ms: number | null;
  estimated_ai_cost_cents: number | null;
  revenue_cents: number | null;
  estimated_profit_cents: number | null;
};
export type RecentSession = {
  session_id: string;
  client_alias: string;
  status: SessionStatus;
  updated_at: string;
  last_seq: number;
};
export type AdminOverviewResponse = {
  schema_version: 1;
  mode: Mode;
  window: OverviewWindow;
  metrics: OverviewMetrics;
  recent_sessions: RecentSession[];
};
export type SubmitOrderRequest = {
  session_id: string;
  recommendation_id: string;
  client_action_id: string;
  confirmed: true;
};
export type OrderAcceptedResponse = {
  schema_version: 1;
  session_id: string;
  client_action_id: string;
  status: "accepted";
};
export type HTTPErrorBody = {
  code: string;
  message: string;
  retryable: boolean;
  details: string[];
};
export type HTTPErrorResponse = {
  schema_version: 1;
  request_id: string;
  error: HTTPErrorBody;
};
type Envelope = {
  schema_version: 1;
  event_id: string;
  seq: number;
  occurred_at: string;
  tenant_id: string;
  session_id: string;
  actor: Actor;
  recipient: Actor | null;
  visibility: Visibility;
  mode: Mode;
};
export type OfficeEvent = Envelope &
  (
    | { type: "session_started"; payload: SessionStartedPayload }
    | { type: "chat_message"; payload: ChatMessagePayload }
    | { type: "agent_status"; payload: AgentStatusPayload }
    | { type: "agent_message"; payload: AgentMessagePayload }
    | { type: "tool_activity"; payload: ToolActivityPayload }
    | { type: "knowledge_retrieved"; payload: KnowledgeRetrievedPayload }
    | { type: "memory_changed"; payload: MemoryChangedPayload }
    | { type: "pattern_identified"; payload: PatternIdentifiedPayload }
    | { type: "discount_proposed"; payload: DiscountProposedPayload }
    | { type: "conflict_detected"; payload: ConflictDetectedPayload }
    | { type: "decision_made"; payload: DecisionMadePayload }
    | { type: "recommendations_ready"; payload: RecommendationsReadyPayload }
    | { type: "cart_changed"; payload: CartChangedPayload }
    | { type: "order_status_changed"; payload: OrderStatusChangedPayload }
    | { type: "error"; payload: EventErrorPayload }
    | { type: "session_closed"; payload: SessionClosedPayload }
  );
