import { test } from "node:test";
import assert from "node:assert/strict";
import { applyEvent, conflicts, mergeEvents } from "./state";
import {
  mockCreate,
  mockHistory,
  mockSend,
  mockSnapshot,
  mockSubmit,
} from "../mocks/server";
import fixture from "../mocks/events.json";
import type { OfficeEvent, SessionSnapshotResponse } from "../types/api";
const events = fixture as OfficeEvent[];
test("conflito resolvido substitui o estado aberto do mesmo ID", () => {
  const list = conflicts(events);
  assert.equal(list.length, 2);
  assert.equal(
    list.find((e) => e.payload.conflict_id === "conflict_1")?.payload.status,
    "resolved",
  );
});
test("replay de eventos é idempotente e não cruza sessões", () => {
  const s = mockSnapshot("sess_1", true);
  assert.strictEqual(applyEvent(s, events[0]), s);
  assert.strictEqual(
    applyEvent(s, { ...events[0], session_id: "outra", seq: 100 }),
    s,
  );
  assert.equal(mergeEvents(events, events).length, events.length);
});
test("mocks filtram eventos administrativos para o comprador", () => {
  assert.ok(
    mockHistory("sess_1", 0, false).events.every(
      (e) => e.visibility !== "admin",
    ),
  );
  assert.equal(mockSnapshot("sess_1", false).agents.length, 0);
});
test("202 simulado não cria imediatamente resposta ou pedido; IDs impedem duplicação", async () => {
  const session = mockCreate();
  assert.ok(!("updated_at" in session));
  const request = {
    session_id: session.session_id,
    client_message_id: "test_message",
    text: "Quero jantar",
    input_mode: "text" as const,
    transcription_id: null,
  };
  await mockSend(request);
  await mockSend(request);
  assert.equal(mockSnapshot(session.session_id, false).messages.length, 1);
  await new Promise((r) => setTimeout(r, 800));
  const s = mockSnapshot(session.session_id, false);
  assert.equal(s.messages.length, 2);
  assert.equal(s.recommendations[0].total_cents, 11800);
  const order = {
    session_id: session.session_id,
    recommendation_id: "rec_1",
    client_action_id: "test_action",
    confirmed: true as const,
  };
  mockSubmit(order);
  mockSubmit(order);
  assert.equal(mockSnapshot(session.session_id, false).cart, null);
  await new Promise((r) => setTimeout(r, 600));
  assert.equal(
    mockHistory(session.session_id, 0, false).events.filter(
      (e) => e.type === "order_status_changed",
    ).length,
    1,
  );
});
