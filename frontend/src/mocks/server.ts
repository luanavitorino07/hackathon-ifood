import catalog from "./agents.json";
import fixture from "./events.json";
import type * as T from "../types/api";
import { applyEvent } from "../services/state";
const events = new Map<string, T.OfficeEvent[]>();
const snapshots = new Map<string, T.SessionSnapshotResponse>();
const seen = new Set<string>();
const iso = () => new Date().toISOString();
export const mockCatalog = catalog as T.AgentCatalogResponse;
function empty(id: string): T.SessionSnapshotResponse {
  return {
    schema_version: 1,
    session: {
      session_id: id,
      client_alias: "Cliente demonstração",
      status: "active",
      mode: "demo",
      created_at: iso(),
      updated_at: iso(),
    },
    last_seq: 0,
    agents: [],
    messages: [],
    recommendations: [],
    cart: null,
  };
}
const sample = fixture as T.OfficeEvent[];
events.set("sess_1", sample);
snapshots.set("sess_1", sample.reduce(applyEvent, empty("sess_1")));
export function mockCreate(): T.SessionCreateResponse {
  const id = "demo_" + Date.now();
  snapshots.set(id, empty(id));
  events.set(id, []);
  const { updated_at, ...session } = snapshots.get(id)!.session;
  return { schema_version: 1, ...session };
}
export function mockSnapshot(id: string, admin: boolean) {
  const s = structuredClone(snapshots.get(id)!);
  if (!s) throw Error("Sessão não encontrada");
  if (!admin) s.agents = [];
  return s;
}
export function mockHistory(
  id: string,
  after: number,
  admin: boolean,
): T.HistoryResponse {
  const list = (events.get(id) || [])
    .filter((e) => e.seq > after && (admin || e.visibility !== "admin"))
    .slice(0, 200);
  return {
    schema_version: 1,
    session_id: id,
    events: list,
    last_seq: list.at(-1)?.seq ?? after,
    has_more: (events.get(id) || []).some(
      (e) =>
        e.seq > (list.at(-1)?.seq ?? after) &&
        (admin || e.visibility !== "admin"),
    ),
  };
}
function emit(
  id: string,
  type: T.OfficeEvent["type"],
  payload: unknown,
  admin = false,
) {
  const list = events.get(id)!;
  const e = {
    schema_version: 1,
    event_id: id + "_" + (list.length + 1),
    seq: list.length + 1,
    occurred_at: iso(),
    tenant_id: "tenant_demo",
    session_id: id,
    type,
    actor: {
      kind:
        type === "chat_message" &&
        (payload as T.ChatMessagePayload).message.role === "customer"
          ? "customer"
          : "agent",
      id: "orchestrator",
    },
    recipient: null,
    visibility: admin ? "admin" : "both",
    mode: "demo",
    payload,
  } as T.OfficeEvent;
  list.push(e);
  snapshots.set(id, applyEvent(snapshots.get(id)!, e));
}
export async function mockSend(r: T.ChatMessageRequest) {
  const key = r.session_id + r.client_message_id;
  if (seen.has(key)) return;
  seen.add(key);
  emit(r.session_id, "chat_message", {
    message: {
      message_id: r.client_message_id,
      role: "customer",
      input_mode: r.input_mode,
      text: r.text,
      created_at: iso(),
    },
  });
  setTimeout(() => {
    for (const e of sample.filter((e) => e.seq >= 3 && e.seq <= 16))
      emit(r.session_id, e.type, e.payload, e.visibility === "admin");
  }, 700);
}
export function mockSubmit(r: T.SubmitOrderRequest) {
  const key = r.session_id + r.client_action_id;
  if (seen.has(key)) return;
  seen.add(key);
  setTimeout(() => {
    for (const e of sample.filter((e) => e.seq >= 17 && e.seq <= 19))
      emit(r.session_id, e.type, e.payload);
  }, 500);
}
export function mockOverview(): T.AdminOverviewResponse {
  return {
    schema_version: 1,
    mode: "demo",
    window: { from: "2026-10-17T00:00:00Z", to: iso() },
    metrics: {
      sessions_started: snapshots.size,
      messages_received: [...snapshots.values()].reduce(
        (n, s) => n + s.messages.filter((m) => m.role === "customer").length,
        0,
      ),
      recommendations_made: [...snapshots.values()].reduce(
        (n, s) => n + s.recommendations.length,
        0,
      ),
      orders_submitted: [...snapshots.values()].filter((s) => s.cart).length,
      orders_confirmed: 0,
      conversion_rate: null,
      average_response_ms: 1200,
      estimated_ai_cost_cents: null,
      revenue_cents: null,
      estimated_profit_cents: null,
    },
    recent_sessions: [...snapshots.values()].map((s) => ({
      session_id: s.session.session_id,
      client_alias: s.session.client_alias,
      status: s.session.status,
      updated_at: s.session.updated_at,
      last_seq: s.last_seq,
    })),
  };
}
