import type { OfficeEvent, SessionSnapshotResponse } from "../types/api";
export function applyEvent(
  s: SessionSnapshotResponse,
  e: OfficeEvent,
): SessionSnapshotResponse {
  if (e.session_id !== s.session.session_id || e.seq <= s.last_seq) return s;
  const next = {
    ...s,
    last_seq: e.seq,
    session: { ...s.session, updated_at: e.occurred_at },
  };
  switch (e.type) {
    case "chat_message":
      next.messages = [
        ...s.messages.filter(
          (m) => m.message_id !== e.payload.message.message_id,
        ),
        e.payload.message,
      ];
      break;
    case "agent_status":
      next.agents = [
        ...s.agents.filter((a) => a.agent_id !== e.payload.agent_id),
        e.payload,
      ];
      break;
    case "recommendations_ready":
      next.recommendations = e.payload.recommendations;
      break;
    case "cart_changed":
      next.cart = e.payload.cart;
      break;
    case "session_closed":
      next.session.status = "closed";
      break;
    // "error" não encerra o atendimento: o status vem do snapshot do backend.
  }
  return next;
}
export function mergeEvents(old: OfficeEvent[], incoming: OfficeEvent[]) {
  const map = new Map(old.map((e) => [e.event_id, e]));
  incoming.forEach((e) => map.set(e.event_id, e));
  return [...map.values()].sort((a, b) => a.seq - b.seq);
}
export function conflicts(events: OfficeEvent[]) {
  const latest = new Map<
    string,
    Extract<OfficeEvent, { type: "conflict_detected" }>
  >();
  for (const e of events)
    if (e.type === "conflict_detected") latest.set(e.payload.conflict_id, e);
  return [...latest.values()];
}
