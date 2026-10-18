import { useEffect, useState } from "react";
import { api } from "../services/api";
import { applyEvent, mergeEvents } from "../services/state";
import type { OfficeEvent, SessionSnapshotResponse } from "../types/api";
export function useSession(id: string | null, admin = false) {
  const [snapshot, setSnapshot] = useState<SessionSnapshotResponse | null>(
    null,
  );
  const [events, setEvents] = useState<OfficeEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setSnapshot(null);
    setEvents([]);
    setError("");
    if (!id) return;
    let hasSnapshot = false;
    let alive = true,
      busy = false,
      cursor = 0;
    let stop = () => {};
    const client = api(admin);
    const accept = (e: OfficeEvent) => {
      if (!alive || e.session_id !== id) return;
      cursor = Math.max(cursor, e.seq);
      setEvents((old) => mergeEvents(old, [e]));
      setSnapshot((old) => (old ? applyEvent(old, e) : old));
    };
    async function recover() {
      if (busy) return;
      busy = true;
      try {
        if (!hasSnapshot) {
          const snapshot = await client.snapshot(id!);
          if (!alive) return;
          setSnapshot(snapshot);
          hasSnapshot = true;
        }
        let more = true;
        while (alive && more) {
          const r = await client.history(id!, cursor);
          if (!alive) return;
          r.events.forEach(accept);
          cursor = Math.max(cursor, r.last_seq);
          more = r.has_more;
        }
        // Some session status changes are projections, not separate SSE events.
        const fresh = await client.snapshot(id!);
        if (alive) setSnapshot((old) => !old || fresh.last_seq >= old.last_seq ? fresh : old);
        if (alive) setError("");
      } catch (e) {
        if (alive) setError(String(e));
      } finally {
        busy = false;
      }
    }
    setLoading(true);
    (async () => {
      try {
        const s = await client.snapshot(id);
        if (!alive) return;
        setSnapshot(s);
        hasSnapshot = true;
        await recover();
        if (alive)
          stop = client.subscribe(id, cursor, accept, () => {
            if (alive) setError("Reconectando… o histórico será recuperado.");
          });
      } catch (e) {
        if (alive) setError(String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    const timer = setInterval(() => {
      void recover();
    }, 2500);
    return () => {
      alive = false;
      clearInterval(timer);
      stop();
    };
  }, [id, admin]);
  return { snapshot, events, error, loading };
}
