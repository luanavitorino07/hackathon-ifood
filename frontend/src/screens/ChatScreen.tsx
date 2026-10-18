import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as Crypto from "expo-crypto";
import { api, ApiError, mocked } from "../services/api";
import { useSession } from "../hooks/useSession";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { Badge, Button, Card, Offer, Pill } from "../components/ui";
import { colors, styles as s, money } from "../theme";
import type {
  ChatMessage,
  ChatMessageRequest,
  Recommendation,
  SubmitOrderRequest,
} from "../types/api";
import { LinearGradient } from "expo-linear-gradient";
import { BrandGradient, Icon, brandGradient } from "../components/Brand";
import { PERSONAS, personaContext } from "../services/personas";

const client = api();
const GREETING =
  "Oi! Eu sou a PedIA 😊 Me conta o que você quer comer, para quantas pessoas e o orçamento, que eu encontro a melhor opção no iFood.";

function time(iso: string) {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function Bubble({ message }: { message: Pick<ChatMessage, "role" | "text" | "input_mode"> & { created_at?: string } }) {
  const mine = message.role === "customer";
  const meta = `${message.input_mode === "audio" ? "Áudio transcrito · " : ""}${message.created_at ? time(message.created_at) : ""}`;
  return (
    <LinearGradient
      colors={mine ? brandGradient : ["#F4F4F5", "#F4F4F5"]}
      style={[
        s.bubble,
        {
          alignSelf: mine ? "flex-end" : "flex-start",
          maxWidth: "86%",
          borderTopRightRadius: mine ? 4 : 20,
          borderTopLeftRadius: mine ? 20 : 4,
          paddingVertical: 12,
          paddingHorizontal: 16,
          gap: 4,
        },
      ]}
    >
      <Text style={[s.text, { fontSize: 16, lineHeight: 23, color: mine ? "#FFFFFF" : colors.ink }]}>
        {message.text}
      </Text>
      {!!meta && (
        <Text style={[s.muted, { fontSize: 12, lineHeight: 16, color: mine ? "#FFE3E4" : "#9A9A9A" }]}>{meta}</Text>
      )}
    </LinearGradient>
  );
}

function Typing() {
  return (
    <View
      accessibilityLabel="PedIA está analisando seu pedido"
      style={[s.bubble, { alignSelf: "flex-start", backgroundColor: "#F4F4F5", borderTopLeftRadius: 4, paddingVertical: 12, flexDirection: "row", alignItems: "center", gap: 10 }]}
    >
      <ActivityIndicator size="small" color={colors.red} />
      <Text style={[s.muted, { fontSize: 14 }]}>Os agentes estão pesquisando e analisando seu pedido…</Text>
    </View>
  );
}

export function ChatScreen({ onBack }: { onBack: () => void }) {
  const [id, setId] = useState<string | null>(null),
    [text, setText] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [transcription, setTranscription] = useState<string | null>(null),
    [review, setReview] = useState<Recommendation | null>(null),
    [accepted, setAccepted] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [persona, setPersona] = useState<string | null>(() => {
    try { return (Platform.OS === "web" && sessionStorage.getItem("pedia_persona")) || null; } catch { return null; }
  });
  const scroll = useRef<ScrollView>(null);
  const pending = useRef<ChatMessageRequest | null>(null);
  const action = useRef<SubmitOrderRequest | null>(null);
  const { snapshot, events, error: syncError, loading } = useSession(id);

  async function create(fresh = false, who: string | null = persona) {
    setBusy(true);
    try {
      if (!fresh && Platform.OS === "web" && !mocked) {
        let saved: string | null = null;
        try { saved = sessionStorage.getItem("pedia_session"); } catch {}
        if (saved) {
          try {
            await client.snapshot(saved);
            setId(saved);
            return;
          } catch (e) { if (!(e instanceof ApiError && e.status === 404)) throw e; }
        }
      }
      const r = await client.create(personaContext(who));
      setId(r.session_id);
      setPersona(who);
      if (Platform.OS === "web" && !mocked) {
        try {
          sessionStorage.setItem("pedia_session", r.session_id);
          if (who) sessionStorage.setItem("pedia_persona", who);
          else sessionStorage.removeItem("pedia_persona");
        } catch {}
      }
      setReview(null);
      setAccepted(false);
      setText("");
      setTranscription(null);
      pending.current = null;
      action.current = null;
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void create();
  }, []);

  async function send(retry = false) {
    if (!id || (!retry && !text.trim())) return;
    setBusy(true);
    setError("");
    const request = retry
      ? pending.current
      : {
          session_id: id,
          client_message_id: Crypto.randomUUID(),
          text: text.trim(),
          input_mode: transcription ? ("audio" as const) : ("text" as const),
          transcription_id: transcription,
        };
    if (!request) {
      setBusy(false);
      return;
    }
    pending.current = request;
    try {
      await client.send(request);
      pending.current = null;
      setText("");
      setTranscription(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function transcribe(uri: string, name: string, mime: string) {
    setBusy(true);
    setTranscribing(true);
    setError("");
    try {
      const r = await client.transcribe(uri, name, mime);
      setText(r.text);
      setTranscription(r.transcription_id);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); setTranscribing(false); }
  }
  const { recording, toggle: toggleRecording } = useAudioRecorder(transcribe, setError);
  async function audio() {
    setBusy(true);
    setError("");
    try {
      const pick = await DocumentPicker.getDocumentAsync({ type: "audio/*", copyToCacheDirectory: true });
      if (pick.canceled) return;
      const file = pick.assets[0];
      await transcribe(file.uri, file.name, file.mimeType || "audio/mp4");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    if (!review || !id) return;
    setBusy(true);
    if (!action.current)
      action.current = {
        session_id: id,
        recommendation_id: review.recommendation_id,
        client_action_id: Crypto.randomUUID(),
        confirmed: true,
      };
    try {
      await client.submit(action.current);
      setAccepted(true);
      setReview(null);
      action.current = null;
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const messages = snapshot?.messages ?? [];
  const waiting = messages.at(-1)?.role === "customer";
  const lastAssistant = messages.map((m) => m.role).lastIndexOf("assistant");
  const order = events.filter((e) => e.type === "order_status_changed").at(-1);
  const eventError = events.filter((e) => e.type === "error").at(-1);
  const recommendations = snapshot?.recommendations ?? [];
  // Cada resposta do bot mantém as recomendações que vieram com ela (o histórico não "some").
  const byMessage = useMemo(() => {
    const map = new Map<string, Recommendation[]>();
    let ready: Recommendation[] | null = null;
    for (const e of events) {
      if (e.type === "recommendations_ready") ready = e.payload.recommendations;
      else if (e.type === "chat_message" && e.payload.message.role === "assistant" && ready) {
        map.set(e.payload.message.message_id, ready);
        ready = null;
      }
    }
    return map;
  }, [events]);
  const offersFor = (list: Recommendation[], latest: boolean) => (
    <View style={{ gap: 14, opacity: latest ? 1 : 0.75 }}>
      {list.map((r, index) => (
        <Offer
          key={r.recommendation_id}
          offer={r}
          highlight={latest && index === 0 && list.length > 1}
          onSelect={
            snapshot?.session.status === "closed"
              ? undefined
              : () => {
                  setReview(r);
                  action.current = null;
                }
          }
        />
      ))}
    </View>
  );
  const fresh = messages.length === 0;
  const offers = (
    <View style={{ gap: 14 }}>
      {recommendations.map((r, index) => (
        <Offer
          key={r.recommendation_id}
          offer={r}
          highlight={index === 0 && recommendations.length > 1}
          onSelect={
            snapshot?.session.status === "closed"
              ? undefined
              : () => {
                  setReview(r);
                  action.current = null;
                }
          }
        />
      ))}
    </View>
  );

  return (
    <View style={[s.page, { maxWidth: 560, width: "100%", alignSelf: "center", borderColor: "#eee", borderLeftWidth: 1, borderRightWidth: 1 }]}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          minHeight: 72,
          borderBottomWidth: 1,
          borderColor: colors.line,
          paddingHorizontal: 16,
          gap: 12,
          backgroundColor: colors.paper,
        }}
      >
        <Pressable accessibilityRole="button" accessibilityLabel="Abrir escritório" onPress={onBack} hitSlop={10}>
          <Icon name="back" color="#ff161e" size={22} />
        </Pressable>
        <BrandGradient style={{ width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center" }}>
          <Text style={{ fontFamily: "InterBold", fontSize: 18, color: "#FFFFFF" }}>P</Text>
        </BrandGradient>
        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={[s.heading, { fontSize: 19, lineHeight: 24 }]}>PedIA</Text>
            {snapshot && (
              <Pill
                text={snapshot.session.mode === "demo" ? "Demo" : "Online"}
                tone={snapshot.session.mode === "demo" ? "amber" : "green"}
              />
            )}
          </View>
          <Text numberOfLines={1} style={[s.muted, { fontSize: 13, lineHeight: 17 }]}>
            {waiting ? "analisando seu pedido…" : persona ? `atendendo ${persona}` : "assistente de pedidos do iFood"}
          </Text>
        </View>
        {id && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Novo atendimento"
            onPress={() => void create(true)}
            disabled={busy || recording}
            hitSlop={10}
            style={({ pressed }) => ({
              opacity: busy || recording ? 0.4 : pressed ? 0.6 : 1,
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              paddingHorizontal: 10,
              paddingVertical: 7,
              borderRadius: 18,
              backgroundColor: colors.redSoft,
            })}
          >
            <Icon name="plus" size={12} color={colors.red} />
            <Text style={{ fontFamily: "InterMedium", fontSize: 13, color: colors.red }}>Novo</Text>
          </Pressable>
        )}
      </View>

      <ScrollView
        ref={scroll}
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}
        contentContainerStyle={{ padding: 16, paddingTop: 20, gap: 12, flexGrow: 1 }}
      >
        <Bubble message={{ role: "assistant", text: GREETING, input_mode: "text" }} />
        {loading && !snapshot && <ActivityIndicator color={colors.red} />}
        {fresh && (
          <View style={{ gap: 8 }}>
            <Text style={[s.muted, { fontSize: 13 }]}>Quem está pedindo? (clientes fictícios da demonstração)</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {PERSONAS.map((p) => {
                const active = p.name === persona;
                return (
                  <Pressable
                    key={p.name ?? "novo"}
                    accessibilityRole="button"
                    accessibilityLabel={`Atender como ${p.name ?? "cliente novo"}`}
                    onPress={() => void create(true, p.name)}
                    disabled={busy}
                    style={({ pressed }) => ({
                      opacity: pressed ? 0.7 : 1,
                      paddingVertical: 8,
                      paddingHorizontal: 12,
                      borderRadius: 14,
                      borderWidth: 1,
                      borderColor: active ? "#FFB3B7" : colors.line,
                      backgroundColor: active ? colors.redSoft : colors.paper,
                      maxWidth: 250,
                    })}
                  >
                    <Text style={{ fontFamily: "InterSemiBold", fontSize: 14, color: colors.ink }}>
                      {p.emoji} {p.name ?? "Cliente novo"}
                    </Text>
                    <Text style={[s.muted, { fontSize: 12, lineHeight: 16 }]}>{p.about}</Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        )}
        {messages.map((m, index) => {
          const own = byMessage.get(m.message_id);
          return (
            <React.Fragment key={m.message_id}>
              <Bubble message={m} />
              {own
                ? offersFor(own, index === lastAssistant)
                : byMessage.size === 0 && index === lastAssistant && recommendations.length > 0 && offers}
            </React.Fragment>
          );
        })}
        {lastAssistant < 0 && recommendations.length > 0 && offers}
        {waiting && <Typing />}
        {review && (
          <Card title="Confirmar compra">
            <Text style={s.text}>
              {review.merchant_name} · {money(review.total_cents)}
            </Text>
            <Text style={s.muted}>
              Compra simulada: o pedido fica registrado neste atendimento, mas nada é enviado ao iFood e nenhum
              pagamento é feito.
            </Text>
            <Button title="Comprar (simulação)" onPress={() => void submit()} disabled={busy} />
            <Button title="Voltar" variant="ghost" onPress={() => setReview(null)} disabled={busy} />
          </Card>
        )}
        {accepted && !order && <Text style={s.muted}>Registrando a compra…</Text>}
        {order?.type === "order_status_changed" && (
          <Card title="Status do pedido">
            <Badge text={order.payload.status === "confirmed" ? "compra registrada (simulação)" : order.payload.status} />
            <Text style={s.text}>{order.payload.summary}</Text>
          </Card>
        )}
        {snapshot?.cart && (
          <Text style={s.muted}>
            Carrinho: {snapshot.cart.status} · {money(snapshot.cart.total_cents)}
          </Text>
        )}
        {eventError?.type === "error" && !waiting && <Text style={s.error}>{eventError.payload.message}</Text>}
        {!!(error || syncError) && (
          <Text accessibilityRole="alert" style={s.error}>
            {error || syncError}
          </Text>
        )}
        {pending.current && (
          <Button title="Tentar o mesmo envio novamente" disabled={busy} onPress={() => void send(true)} />
        )}
        {!id && <Button title="Conectar novamente" onPress={() => void create()} disabled={busy} />}
      </ScrollView>

      <View style={{ padding: 12, paddingBottom: 16, gap: 8, borderTopWidth: 1, borderColor: colors.line }}>
        {transcribing && <Text style={s.muted}>Transcrevendo áudio… aguarde e revise o texto.</Text>}
        {recording && <Text style={[s.muted, { color: colors.red }]}>● Gravando… toque no microfone para finalizar.</Text>}
        {!!transcription && (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <Pill text={mocked ? "Transcrição simulada — revise" : "Revise a transcrição antes de enviar"} tone="amber" />
            <Pressable
              accessibilityRole="button"
              onPress={() => {
                setTranscription(null);
                setText("");
              }}
            >
              <Text style={{ fontFamily: "InterMedium", fontSize: 13, color: colors.red }}>Descartar</Text>
            </Pressable>
          </View>
        )}
        <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 8 }}>
          <TextInput
            accessibilityLabel="Mensagem"
            placeholder="Escreva seu pedido…"
            value={text}
            onChangeText={setText}
            multiline
            editable={!busy && !recording}
            placeholderTextColor="#B5B5B5"
            onKeyPress={(e) => {
              const key = e.nativeEvent as unknown as { key: string; shiftKey?: boolean };
              if (Platform.OS === "web" && key.key === "Enter" && !key.shiftKey) {
                (e as unknown as { preventDefault: () => void }).preventDefault?.();
                void send();
              }
            }}
            style={[s.input, { flex: 1, minWidth: 0, fontSize: 16, maxHeight: 120 }]}
          />
          <Button
            title="Enviar arquivo de áudio"
            icon={Platform.OS === "web" ? "file" : "mic"}
            variant="ghost"
            onPress={() => void audio()}
            disabled={busy || !id || recording}
          />
          {Platform.OS === "web" && (
            <Button
              title={recording ? "Finalizar gravação" : "Gravar áudio"}
              icon="mic"
              variant={recording ? "primary" : "ghost"}
              onPress={() => void toggleRecording()}
              disabled={busy || !id}
            />
          )}
          <Button
            title={busy ? "Enviando" : transcription ? "Confirmar texto e enviar" : "Enviar"}
            icon="send"
            onPress={() => void send()}
            disabled={busy || recording || !id || !text.trim() || snapshot?.session.status === "closed" || !!pending.current}
          />
        </View>
      </View>
    </View>
  );
}
