import { test } from "node:test";
import assert from "node:assert/strict";
import { computeExecutive, type SessionHistory } from "./executive";
import type { OfficeEvent } from "../types/api";

let seq = 0;
const ev = (type: string, payload: unknown, extra: Partial<OfficeEvent> = {}, at = "2026-10-18T10:00:00Z") =>
  ({
    schema_version: 1, event_id: `e${++seq}`, seq, occurred_at: at, tenant_id: "t", session_id: "s1",
    type, actor: { kind: "agent", id: "orchestrator" }, recipient: null, visibility: "admin", mode: "demo",
    payload, ...extra,
  }) as unknown as OfficeEvent;

const rec = (total: number) => ({
  recommendation_id: "r1", merchant_id: "m", merchant_name: "Pizzaria", items: [], currency: "BRL",
  subtotal_cents: total, delivery_fee_cents: 0, other_fees_cents: 0, discount_cents: 0, total_cents: total,
  eta_minutes: 30, reasons: [], warnings: [], data_origin: "demo",
});

const history: SessionHistory = {
  session_id: "s1", client_alias: "Cliente #1", status: "active", updated_at: "2026-10-18T10:00:05Z",
  events: [
    ev("chat_message", { message: { message_id: "m1", role: "customer", input_mode: "text", text: "pizza", created_at: "" } }, {}, "2026-10-18T10:00:00Z"),
    ev("agent_message", { message_id: "a", task_id: "t", channel: "proposal", summary: "3 oferta(s)" }, { actor: { kind: "agent", id: "researcher" }, recipient: { kind: "agent", id: "orchestrator" } }),
    ev("tool_activity", { call_id: "c", tool_name: "offer_search", provider: "ifood_mcp", status: "succeeded", duration_ms: 10, summary: "ok" }),
    ev("tool_activity", { call_id: "c2", tool_name: "raciocinio_ia", provider: "internal", status: "succeeded", duration_ms: null, summary: "IA consultada" }, { recipient: { kind: "agent", id: "curator" } }),
    ev("tool_activity", { call_id: "c3", tool_name: "raciocinio_ia", provider: "internal", status: "failed", duration_ms: null, summary: "cota da IA esgotada; regra de reserva usada" }, { recipient: { kind: "agent", id: "sales_strategist" } }),
    ev("agent_message", { message_id: "b", task_id: "t", channel: "proposal", summary: "IA julgou 3 item(ns): 1 atendem ao pedido; descartados, ex.: Pastel de Pizza: não é pizza." }, { actor: { kind: "agent", id: "curator" }, recipient: { kind: "agent", id: "orchestrator" } }),
    ev("recommendations_ready", { recommendations: [rec(9000)] }),
    ev("discount_proposed", { proposal_id: "d", recommendation_id: "r1", discount_type: "percent", discount_bps: 500, discount_cents: 450, estimated_profit_delta_cents: 120, status: "suggested", requires_approval: true, reason: "x" }),
    ev("memory_changed", { scope: "customer", keys: ["requests"], summary: "Pedido registrado no histórico do cliente: pizza" }),
    ev("decision_made", { decision_id: "d1", recommendation_id: "r1", summary: "Recomendação principal: Pizzaria", reasons: [], limitations: [] }),
    ev("chat_message", { message: { message_id: "m2", role: "assistant", input_mode: "text", text: "Sugiro", created_at: "" } }, {}, "2026-10-18T10:00:04Z"),
    ev("agent_message", { message_id: "c", task_id: "t", channel: "resolution", summary: "Pesquisa reaproveitada, sem nova busca: 3 oferta(s)" }),
  ],
};

test("indicadores executivos vêm dos eventos", () => {
  const x = computeExecutive([history], (id) => ({ curator: "Curador", sales_strategist: "Estrategista" })[id] ?? id);
  assert.equal(x.sessions, 1);
  assert.equal(x.withOrderIntent, 1);
  assert.equal(x.withRecommendation, 1);
  assert.equal(x.averageTicketCents, 9000);
  assert.equal(x.averageResponseMs, 4000);
  assert.deepEqual([x.aiCalls, x.aiSucceeded], [2, 1]);
  assert.deepEqual(x.aiFailureReasons, [{ label: "cota da IA esgotada", value: 1 }]);
  assert.deepEqual([x.searches, x.realSearches, x.reusedSearches], [1, 1, 1]);
  assert.deepEqual([x.discountsSuggested, x.discountSuggestedCents, x.profitDeltaCents], [1, 450, 120]);
  assert.deepEqual(x.topDishes, [{ label: "pizza", value: 1 }]);
  assert.deepEqual(x.topMerchants, [{ label: "Pizzaria", value: 1 }]);
  assert.equal(x.decisions[0].summary, "Pizzaria");
  assert.equal(x.highlights[0].text, "Descartou Pastel de Pizza: não é pizza");
});

test("sem dados nada é inventado", () => {
  const x = computeExecutive([]);
  assert.equal(x.averageTicketCents, null);
  assert.equal(x.recommendationRate, null);
  assert.equal(x.averageResponseMs, null);
});
