import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as Crypto from "expo-crypto";
import { api, mocked } from "../services/api";
import { useSession } from "../hooks/useSession";
import { Badge, Button, Card, Offer } from "../components/ui";
import { styles as s, money } from "../theme";
import type {
  ChatMessageRequest,
  Recommendation,
  SubmitOrderRequest,
} from "../types/api";
import { LinearGradient } from "expo-linear-gradient";
import { Icon, brandGradient } from "../components/Brand";
const client = api();
export function ChatScreen({ onBack }: { onBack: () => void }) {
  const [id, setId] = useState<string | null>(null),
    [text, setText] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [transcription, setTranscription] = useState<string | null>(null),
    [review, setReview] = useState<Recommendation | null>(null),
    [accepted, setAccepted] = useState(false);
  const pending = useRef<ChatMessageRequest | null>(null);
  const action = useRef<SubmitOrderRequest | null>(null);
  const { snapshot, events, error: syncError, loading } = useSession(id);
  async function create() {
    setBusy(true);
    try {
      const r = await client.create();
      setId(r.session_id);
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
  async function audio() {
    setBusy(true);
    setError("");
    try {
      const pick = await DocumentPicker.getDocumentAsync({
        type: "audio/*",
        copyToCacheDirectory: true,
      });
      if (pick.canceled) return;
      const file = pick.assets[0];
      const r = await client.transcribe(
        file.uri,
        file.name,
        file.mimeType || "audio/m4a",
      );
      setText(r.text);
      setTranscription(r.transcription_id);
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
  const order = events.filter((e) => e.type === "order_status_changed").at(-1);
  const eventError = events.filter((e) => e.type === "error").at(-1);
  return (
    <View
      style={[
        s.page,
        {
          maxWidth: 520,
          width: "100%",
          alignSelf: "center",
          borderColor: "#eee",
          borderWidth: 1,
        },
      ]}
    >
      <View
        style={[
          s.card,
          {
            borderRadius: 0,
            flexDirection: "row",
            alignItems: "center",
            minHeight: 82,
            borderWidth: 0,
            borderBottomWidth: 1,
            paddingHorizontal: 20,
            gap: 14,
          },
        ]}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Abrir escritório"
          onPress={onBack}
        >
          <Icon name="back" color="#ff161e" size={26} />
        </Pressable>
        <View
          style={[
            s.icon,
            {
              width: 44,
              height: 44,
              backgroundColor: "#e5e5e5",
              borderRadius: 30,
            },
          ]}
        ></View>
        <Text style={s.heading}>PedIA</Text>
        <View style={{ flex: 1 }} />
        <Icon name="more" color="#777" size={19} />
        {snapshot && (
          <Badge
            text={
              snapshot.session.mode === "demo" ? "Demonstração" : "Conectado"
            }
          />
        )}
      </View>
      <ScrollView
        contentContainerStyle={[
          s.content,
          { padding: 22, paddingTop: 28, gap: 28 },
        ]}
      >
        {loading && <ActivityIndicator color="#ff343e" />}
        {!snapshot?.messages.length && (
          <Text style={s.text}>
            Oi! Vou te ajudar a encontrar uma opção dentro do seu orçamento. O
            que você gostaria de pedir?
          </Text>
        )}
        {snapshot?.messages.map((m) => (
          <LinearGradient
            colors={
              m.role === "customer"
                ? brandGradient
                : ["transparent", "transparent"]
            }
            key={m.message_id}
            style={[
              s.bubble,
              {
                alignSelf: m.role === "customer" ? "flex-end" : "flex-start",
                borderTopRightRadius: m.role === "customer" ? 0 : 19,
                padding: m.role === "customer" ? 15 : 0,
                maxWidth: m.role === "customer" ? "80%" : "92%",
              },
            ]}
          >
            <Text
              style={[
                s.text,
                { color: m.role === "customer" ? "white" : "#373737" },
              ]}
            >
              {m.text}
            </Text>
            <Text
              style={[
                s.muted,
                { color: m.role === "customer" ? "#fff" : "#888" },
              ]}
            >
              {m.input_mode === "audio" ? "Áudio transcrito · " : ""}
              {new Date(m.created_at).toLocaleTimeString("pt-BR", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </Text>
          </LinearGradient>
        ))}
        {snapshot?.recommendations.map((r) => (
          <Offer
            key={r.recommendation_id}
            offer={r}
            onSelect={
              snapshot.session.status === "closed"
                ? undefined
                : () => {
                    setReview(r);
                    action.current = null;
                  }
            }
          />
        ))}
        {review && (
          <Card title="Confirmar submissão">
            <Text style={s.text}>
              {review.merchant_name} · {money(review.total_cents)}
            </Text>
            <Text style={s.text}>
              {snapshot?.session.mode === "demo"
                ? "Este pedido será apenas simulado."
                : "Confirme os itens e valores para submeter. O pagamento não é executado aqui."}
            </Text>
            <Button
              title="Confirmar e submeter pedido"
              onPress={() => void submit()}
              disabled={busy}
            />
            <Button
              title="Voltar"
              onPress={() => setReview(null)}
              disabled={busy}
            />
          </Card>
        )}
        {accepted && !order && (
          <Text style={s.text}>
            Solicitação aceita. Aguardando o resultado do pedido…
          </Text>
        )}
        {order?.type === "order_status_changed" && (
          <Card title="Status do pedido">
            <Badge text={order.payload.status} />
            <Text style={s.text}>{order.payload.summary}</Text>
          </Card>
        )}
        {snapshot?.cart && (
          <Text style={s.text}>
            Carrinho: {snapshot.cart.status} ·{" "}
            {money(snapshot.cart.total_cents)}
          </Text>
        )}
        {eventError?.type === "error" && (
          <Text style={s.error}>{eventError.payload.message}</Text>
        )}
        {(error || syncError) && (
          <Text accessibilityRole="alert" style={s.error}>
            {error || syncError}
          </Text>
        )}
        {pending.current && (
          <Button
            title="Tentar o mesmo envio novamente"
            disabled={busy}
            onPress={() => void send(true)}
          />
        )}{" "}
        {!id && (
          <Button
            title="Conectar novamente"
            onPress={() => void create()}
            disabled={busy}
          />
        )}
      </ScrollView>
      <View style={{ padding: 20, paddingBottom: 28, gap: 10 }}>
        {transcription && (
          <>
            <Badge
              text={
                mocked
                  ? "Transcrição simulada — revise o texto"
                  : "Revise a transcrição antes de enviar"
              }
            />
            <Button
              title="Descartar transcrição"
              onPress={() => {
                setTranscription(null);
                setText("");
              }}
            />
          </>
        )}
        <View
          style={[s.row, { alignItems: "center", gap: 8, flexWrap: "nowrap" }]}
        >
          <TextInput
            accessibilityLabel="Mensagem"
            placeholder="Inicie uma conversa com a PedIA…"
            value={text}
            onChangeText={setText}
            multiline
            editable={!busy}
            placeholderTextColor="#cfcfcf"
            style={[
              s.input,
              {
                flex: 1,
                minWidth: 80,
                shadowColor: "#000",
                shadowOffset: { width: 0, height: 2 },
                shadowOpacity: 0.1,
                shadowRadius: 3,
                elevation: 2,
              },
            ]}
          />
          <Button
            title="Enviar arquivo de áudio"
            icon="mic"
            onPress={() => void audio()}
            disabled={busy || !id}
          />
          <Button
            title={busy ? "Enviando" : "Enviar"}
            icon="send"
            onPress={() => void send()}
            disabled={
              busy ||
              !id ||
              !text.trim() ||
              snapshot?.session.status === "closed" ||
              !!pending.current
            }
          />
        </View>
      </View>
    </View>
  );
}
