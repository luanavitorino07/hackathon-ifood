import { Platform } from "react-native";
import EventSource from "react-native-sse";
import type * as T from "../types/api";
import * as mock from "../mocks/server";
export const mocked = process.env.EXPO_PUBLIC_USE_MOCKS === "true";
const base =
  process.env.EXPO_PUBLIC_API_URL?.trim() ||
  (Platform.OS === "web" ? "/api/v1" : "http://localhost:8000/api/v1");
const path = (id: string) => "/sessions/" + encodeURIComponent(id);
export class ApiError extends Error {
  constructor(
    public status: number,
    public body: T.HTTPErrorResponse,
  ) {
    super(body.error.message);
  }
}
export function api(admin = false) {
  const headers: Record<string, string> =
    process.env.EXPO_PUBLIC_DEMO_ADMIN !== "false"
      ? { "X-Demo-Role": admin ? "admin" : "customer" }
      : {};
  async function request<R>(url: string, body?: unknown, timeout = 20000): Promise<R> {
    const form = body instanceof FormData;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(base + url, {
        method: body === undefined ? "GET" : "POST",
        credentials: "include",
        signal: controller.signal,
        headers: {
          ...headers,
          ...(body !== undefined && !form
            ? { "Content-Type": "application/json" }
            : {}),
          ...(body !== undefined && process.env.EXPO_PUBLIC_CSRF_TOKEN
            ? { "X-CSRF-Token": process.env.EXPO_PUBLIC_CSRF_TOKEN }
            : {}),
        },
        body:
          body === undefined ? undefined : form ? body : JSON.stringify(body),
      });
      if (!response.ok) {
        const b = await response.json().catch(() => null);
        throw b?.error
          ? new ApiError(response.status, b)
          : new Error("Falha HTTP " + response.status);
      }
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }
  return {
    create: (
      initial_context: T.InitialContext | null = null,
    ): Promise<T.SessionCreateResponse> =>
      mocked
        ? Promise.resolve(mock.mockCreate())
        : request("/sessions", { client_id: null, initial_context }),
    catalog: (): Promise<T.AgentCatalogResponse> =>
      mocked ? Promise.resolve(mock.mockCatalog) : request("/agents"),
    overview: (): Promise<T.AdminOverviewResponse> =>
      mocked
        ? Promise.resolve(mock.mockOverview())
        : request("/admin/overview"),
    snapshot: (id: string): Promise<T.SessionSnapshotResponse> =>
      mocked
        ? Promise.resolve(mock.mockSnapshot(id, admin))
        : request(path(id) + "/snapshot"),
    history: (id: string, after = 0): Promise<T.HistoryResponse> =>
      mocked
        ? Promise.resolve(mock.mockHistory(id, after, admin))
        : request(path(id) + "/history?after_seq=" + after + "&limit=200"),
    send: async (r: T.ChatMessageRequest) =>
      mocked
        ? mock.mockSend(r)
        : request<T.ChatAcceptedResponse>("/chat/messages", r),
    submit: async (r: T.SubmitOrderRequest) =>
      mocked
        ? mock.mockSubmit(r)
        : request<T.OrderAcceptedResponse>("/orders/submit", r),
    transcribe: async (
      uri: string,
      name: string,
      mime: string,
    ): Promise<T.TranscriptionResponse> => {
      if (mocked)
        return {
          schema_version: 1,
          transcription_id: "demo_transcription",
          text: "Quero comida para quatro pessoas até R$ 120, com opção vegetariana.",
          language: "pt-BR",
          requires_confirmation: true,
        };
      const form = new FormData();
      if (Platform.OS === "web") {
        const blob = await (await fetch(uri)).blob();
        form.append("audio", blob, name);
      } else form.append("audio", { uri, name, type: mime } as unknown as Blob);
      form.append("language", "pt-BR");
      return request("/audio/transcriptions", form, 180000);
    },
    subscribe: (
      id: string,
      after: number,
      onEvent: (e: T.OfficeEvent) => void,
      onError: () => void,
    ) => {
      if (mocked) return () => {};
      const stream = new EventSource<"office_event">(
        base + path(id) + "/events?after_seq=" + after,
        { headers, withCredentials: true, pollingInterval: 3000 },
      );
      stream.addEventListener("office_event", (e) => {
        try {
          if (e.data) onEvent(JSON.parse(e.data));
        } catch {
          onError();
        }
      });
      stream.addEventListener("error", onError);
      return () => stream.close();
    },
  };
}
