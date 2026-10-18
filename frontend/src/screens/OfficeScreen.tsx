import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";

import { api } from "../services/api";
import { useSession } from "../hooks/useSession";
import { conflicts } from "../services/state";
import { Badge, Card, Metric, Offer } from "../components/ui";
import {
  AgentIcon,
  BrandGradient,
  Icon,
} from "../components/Brand";
import { AgentGraph } from "../components/AgentGraph";
import { styles as s, colors, money, agentStatusLabel, relativeTime, sessionStatusLabel } from "../theme";

import type {
  AdminOverviewResponse,
  AgentDefinition,
  OfficeEvent,
} from "../types/api";

export type OfficeTab =
  | "Dashboard"
  | "Painel de Agentes"
  | "Conflitos";

const client = api(true);

function eventDescription(event: OfficeEvent): string {
  switch (event.type) {
    case "chat_message":
      return event.payload.message.text;

    case "decision_made":
      return [
        event.payload.summary,
        ...event.payload.reasons,
        ...event.payload.limitations,
      ].join("\n");

    case "knowledge_retrieved":
      return event.payload.sources
        .map((source) => source.title)
        .join(", ");

    case "pattern_identified":
      return [
        event.payload.description,
        `Origem: ${event.payload.basis}`,
        `Evidências: ${event.payload.evidence_count}`,
      ].join("\n");

    case "discount_proposed":
      return [
        event.payload.reason,
        `Status: ${event.payload.status}`,
        `Impacto estimado: ${money(
          event.payload.estimated_profit_delta_cents,
        )}`,
      ].join("\n");

    case "conflict_detected":
      return event.payload.description;

    case "error":
      return event.payload.message;

    case "session_started":
      return event.payload.client_alias;

    case "recommendations_ready":
      return `${event.payload.recommendations.length} recomendações`;

    case "cart_changed":
      return `Carrinho: ${event.payload.cart.status}`;

    default:
      return event.payload.summary ?? "Sem resumo";
  }
}

type CommunicationItem = {
  agent: AgentDefinition;
  count: number;
};

// Gráfico de barras VERTICAIS.
// Os nomes ficam em uma linha separada para as barras
// permanecerem alinhadas mesmo quando um nome quebra.
function CommunicationChart({
  items,
}: {
  items: CommunicationItem[];
}) {
  const maximum = Math.max(
    1,
    ...items.map((item) => item.count),
  );

  const plotHeight = 140;

  if (!items.length) {
    return (
      <Text style={s.empty}>
        Nenhum destinatário disponível.
      </Text>
    );
  }

  return (
    <View style={local.chartContainer}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator
        contentContainerStyle={local.chartScroll}
      >
        <View style={local.chart}>
          {/* Área das barras verticais */}
          <View style={local.chartPlot}>
            {items.map(({ agent, count }) => (
              <View
                key={agent.agent_id}
                style={local.chartColumn}
              >
                <Text style={local.chartValue}>
                  {count}
                </Text>

                <BrandGradient
                  style={[
                    local.chartBar,
                    {
                      height:
                        count === 0
                          ? 2
                          : (count / maximum) * plotHeight,
                    },
                  ]}
                />
              </View>
            ))}
          </View>

          {/* Nomes alinhados abaixo da linha de base */}
          <View style={local.chartLabels}>
            {items.map(({ agent }) => (
              <View
                key={agent.agent_id}
                style={local.chartLabelColumn}
              >
                <Text style={local.chartLabel}>
                  {agent.name}
                </Text>
              </View>
            ))}
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

export function OfficeScreen({ tab }: { tab: OfficeTab }) {
  const width = useWindowDimensions().width;

  const wide = width >= 1100;
  const individualColumns = width >= 1350;

  const [overview, setOverview] =
    useState<AdminOverviewResponse | null>(null);

  const [agents, setAgents] =
    useState<AgentDefinition[]>([]);

  const [sessionId, setSessionId] =
    useState<string | null>(null);

  const [selectedAgent, setSelectedAgent] = useState("");
  const [error, setError] = useState("");

  const [filter, setFilter] =
    useState<"all" | "open" | "resolved">("all");

  const {
    snapshot,
    events,
    loading,
    error: sessionError,
  } = useSession(sessionId, true);

  useEffect(() => {
    let alive = true;
    let busy = false;

    async function load() {
      if (busy) return;

      busy = true;

      try {
        const [nextOverview, catalog] = await Promise.all([
          client.overview(),
          client.catalog(),
        ]);

        if (!alive) return;

        setOverview(nextOverview);
        setAgents(catalog.agents);
        setError("");

        setSessionId((current) => {
          const exists = nextOverview.recent_sessions.some(
            (session) => session.session_id === current,
          );
          // Abrir a página cria atendimentos vazios; prefira o mais recente com atividade.
          const active = nextOverview.recent_sessions.find((session) => session.last_seq > 2);
          return current && exists
            ? current
            : active?.session_id ?? nextOverview.recent_sessions[0]?.session_id ?? null;
        });

        setSelectedAgent((current) => {
          const exists = catalog.agents.some(
            (agent) => agent.agent_id === current,
          );

          return exists
            ? current
            : catalog.agents[0]?.agent_id ?? "";
        });
      } catch (cause) {
        if (alive) {
          setError(String(cause));
        }
      } finally {
        busy = false;
      }
    }

    void load();

    const timer = setInterval(() => void load(), 5000);

    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const allConflicts = conflicts(events);

  const openConflicts = allConflicts.filter(
    (event) => event.payload.status === "open",
  );

  const resolvedConflicts = allConflicts.filter(
    (event) => event.payload.status === "resolved",
  );

  const visibleConflicts =
    filter === "all"
      ? allConflicts
      : allConflicts.filter(
          (event) => event.payload.status === filter,
        );

  const selectedDefinition = agents.find(
    (agent) => agent.agent_id === selectedAgent,
  );

  const runtime = snapshot?.agents.find(
    (agent) => agent.agent_id === selectedAgent,
  );

  const communications = events.filter(
    (event) => event.type === "agent_message",
  );

  const individualEvents = events.filter(
    (event) =>
      event.actor.id === selectedAgent ||
      event.recipient?.id === selectedAgent,
  );

  const decisions = individualEvents.filter(
    (event) => event.type === "decision_made",
  );

  const reasons = decisions.flatMap(
    (event) => event.payload.reasons,
  );

  const reasonCounts = [...new Set(reasons)]
    .map((reason) => ({
      reason,
      count: reasons.filter((item) => item === reason).length,
    }))
    .sort((a, b) => b.count - a.count);

  const communicationCounts: CommunicationItem[] = agents
    .filter((agent) => agent.agent_id !== selectedAgent)
    .map((agent) => ({
      agent,
      count: communications.filter(
        (event) =>
          event.actor.id === selectedAgent &&
          event.recipient?.id === agent.agent_id,
      ).length,
    }));

  const agentName = (id: string) =>
    agents.find((agent) => agent.agent_id === id)?.name ??
    id;

  const metrics = overview?.metrics;

  const auditEvents = events.filter((event) =>
    [
      "decision_made",
      "knowledge_retrieved",
      "memory_changed",
      "pattern_identified",
      "discount_proposed",
      "tool_activity",
      "error",
      "order_status_changed",
    ].includes(event.type),
  );

  function renderAgents(compact: boolean) {
    return agents.map((agent) => {
      const state = snapshot?.agents.find(
        (item) => item.agent_id === agent.agent_id,
      );

      const status = !agent.enabled
        ? "Indisponível"
        : state
          ? agentStatusLabel[state.status] ?? state.status
          : "Sem atividade";

      const dotColor = !agent.enabled
        ? "#CCCCCC"
        : state?.status === "error"
          ? colors.red
          : state
            ? "#95EF80"
            : "#CCCCCC";

      return (
        <Pressable
          key={agent.agent_id}
          accessibilityRole="button"
          accessibilityState={{
            selected: selectedAgent === agent.agent_id,
          }}
          onPress={() => setSelectedAgent(agent.agent_id)}
          style={[
            s.card,
            local.agentCard,
            compact
              ? local.agentCardHorizontal
              : local.agentCardVertical,
            !compact &&
              selectedAgent === agent.agent_id &&
              local.selectedCard,
          ]}
        >
          <AgentIcon id={agent.agent_id} size={44} />

          <View
            style={
              compact
                ? { flex: 1, minWidth: 0 }
                : undefined
            }
          >
            <Text style={s.text}>{agent.name}</Text>

            {!compact && (
              <Text style={s.muted}>{agent.role}</Text>
            )}
          </View>

          <View style={local.status}>
            <Text style={s.muted}>{status}</Text>

            <View
              style={[
                local.statusDot,
                { backgroundColor: dotColor },
              ]}
            />
          </View>
        </Pressable>
      );
    });
  }

  function renderConflicts() {
    return visibleConflicts.map((event) => (
      <Card key={event.payload.conflict_id}>
        <Text style={s.muted}>
          {overview?.recent_sessions.find((r) => r.session_id === event.session_id)?.client_alias ?? "Atendimento"}
          {" · "}
          {relativeTime(event.occurred_at)}
        </Text>

        <View style={local.conflictContent}>
          <View style={{ width: 42 }}>
            <Icon
              name="planner"
              color="#FF545C"
              size={30}
            />

            <View style={{ alignSelf: "flex-end" }}>
              <Icon
                name="strategist"
                color="#FF545C"
                size={25}
              />
            </View>
          </View>

          <View style={{ flex: 1, gap: 6 }}>
            <Text
              style={[
                s.text,
                { fontFamily: "InterMedium" },
              ]}
            >
              {event.payload.agent_ids
                .map(agentName)
                .join(" × ")}
            </Text>

            <Text style={s.muted}>
              {event.payload.description}
            </Text>
          </View>
        </View>

        <View style={local.conflictFooter}>
          <Text style={s.muted}>
            {new Date(
              event.occurred_at,
            ).toLocaleTimeString("pt-BR")}
          </Text>

          <Badge
            text={
              event.payload.status === "open"
                ? "Em aberto"
                : "Concluído"
            }
          />
        </View>
      </Card>
    ));
  }

  const sessionPicker = (
    <View style={{ gap: 10 }}>
      <View style={local.conflictFooter}>
        <Text style={s.muted}>
          Atendimento selecionado
        </Text>

        {overview && (
          <Badge
            text={
              overview.mode === "demo"
                ? "Demonstração"
                : "Conectado à API"
            }
          />
        )}
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 10 }}
      >
        {overview?.recent_sessions
          .filter((session) => session.last_seq > 1 || session.session_id === sessionId)
          .map((session) => (
          <Pressable
            key={session.session_id}
            accessibilityRole="button"
            onPress={() =>
              setSessionId(session.session_id)
            }
            style={[
              local.sessionPill,
              sessionId === session.session_id &&
                local.selectedCard,
            ]}
          >
            <Text style={[s.muted, { fontSize: 14 }]}>
              <Text style={{ fontFamily: "InterSemiBold", color: colors.ink }}>{session.client_alias}</Text>
              {" · "}
              {relativeTime(session.updated_at)}
              {" · "}
              {sessionStatusLabel[session.status] ?? session.status}
            </Text>
          </Pressable>
        ))}
      </ScrollView>

      {!overview?.recent_sessions.length && (
        <Text style={s.empty}>
          Inicie uma conversa no chatbot para acompanhar
          um atendimento.
        </Text>
      )}
    </View>
  );

  return (
    <ScrollView
      style={s.page}
      contentContainerStyle={[
        s.content,
        { padding: wide ? 32 : 20 },
      ]}
    >
      <View style={{ gap: 8 }}>
        <Text style={s.title}>{tab === "Painel de Agentes" ? "Painel de Agentes" : tab === "Conflitos" ? "Conflitos" : "Dashboard"}</Text>

        {tab === "Conflitos" && (
          <>
            <Text style={s.muted}>
              Acompanhe divergências entre os agentes
              deste atendimento.
            </Text>
          </>
        )}
      </View>

      {!!(error || sessionError) && (
        <Text accessibilityRole="alert" style={s.error}>
          {error || sessionError}
        </Text>
      )}

      {(!overview || loading) && !error && (
        <ActivityIndicator color={colors.red} />
      )}

      {tab === "Dashboard" && (
        <>
          <Text style={s.heading}>Visão geral</Text>

          <View style={s.row}>
            <Metric
              label="Atendimentos iniciados"
              value={metrics?.sessions_started ?? "—"}
            />

            <Metric
              label="Recomendações feitas"
              value={metrics?.recommendations_made ?? "—"}
            />

            <Metric
              label="Mensagens recebidas"
              value={metrics?.messages_received ?? "—"}
            />

            <Metric
              label="Pedidos confirmados"
              value={metrics?.orders_confirmed ?? "—"}
            />

            <View
              style={[
                s.card,
                {
                  flexGrow: 1,
                  minWidth: 170,
                  borderColor: "#FFA7AC",
                },
              ]}
            >
              <Text
                style={[s.metric, { color: colors.red }]}
              >
                {openConflicts.length}
              </Text>

              <Text
                style={[s.muted, { color: colors.red }]}
              >
                Conflitos abertos no atendimento
              </Text>
            </View>
          </View>
        </>
      )}

      {tab !== "Painel de Agentes" && sessionPicker}

      {tab === "Dashboard" && (
        <View
          style={{
            flexDirection: wide ? "row" : "column",
            gap: 28,
            alignItems: "flex-start",
          }}
        >
          <View
            style={{
              width: wide ? "40%" : "100%",
              gap: 14,
            }}
          >
            <Text style={s.heading}>Agentes</Text>
            {renderAgents(true)}
          </View>

          <View
            style={{
              flex: 1,
              width: wide ? undefined : "100%",
              gap: 14,
            }}
          >
            <Text style={s.heading}>Conflitos</Text>

            {renderConflicts()}

            {!allConflicts.length && (
              <Text style={s.empty}>
                Nenhum conflito registrado nesta sessão.
              </Text>
            )}
          </View>
        </View>
      )}

      {tab === "Conflitos" && (
        <>
          <View style={s.row}>
            <Metric
              label="Conflitos detectados"
              value={allConflicts.length}
            />

            <Metric
              label="Abertos"
              value={openConflicts.length}
            />

            <Metric
              label="Resolvidos"
              value={resolvedConflicts.length}
            />
          </View>

          <Card title="Conflitos recentes">
            <View style={s.row}>
              {(
                [
                  ["all", "Todos"],
                  ["open", "Abertos"],
                  ["resolved", "Resolvidos"],
                ] as const
              ).map(([value, label]) => (
                <Pressable
                  key={value}
                  accessibilityRole="button"
                  onPress={() => setFilter(value)}
                  style={[
                    local.sessionPill,
                    filter === value &&
                      local.selectedCard,
                  ]}
                >
                  <Text style={s.text}>{label}</Text>
                </Pressable>
              ))}
            </View>

            <View style={{ gap: 20 }}>
              {renderConflicts()}

              {!visibleConflicts.length && (
                <Text style={s.empty}>
                  Nenhum conflito neste filtro.
                </Text>
              )}
            </View>
          </Card>
        </>
      )}

      {tab === "Painel de Agentes" && (
        <>
          <Text style={s.heading}>
            Estatísticas gerais
          </Text>

          <View style={s.row}>
            {renderAgents(false)}
          </View>

          <Text style={s.heading}>
            Análise individual
          </Text>

          <Card>
            <View style={local.conflictContent}>
              <AgentIcon
                id={selectedAgent}
                size={34}
              />

              <Text style={s.heading}>
                {selectedDefinition?.name ??
                  "Selecione um agente"}
              </Text>
            </View>

            <View
              style={{
                flexDirection: individualColumns
                  ? "row"
                  : "column",
                gap: 28,
                alignItems: "stretch",
              }}
            >
              {/* Coluna 1: contagens */}
              <View
                style={[
                  local.analysisColumn,
                  individualColumns && {
                    flex: 0.85,
                  },
                ]}
              >
                <Metric
                  label="Atividades registradas"
                  value={individualEvents.length}
                />

                <Metric
                  label="Ferramentas com falha"
                  value={
                    individualEvents.filter(
                      (event) =>
                        event.type === "tool_activity" &&
                        event.payload.status === "failed",
                    ).length
                  }
                />

                <Text style={s.muted}>
                  {runtime?.summary ??
                    "Nenhuma tarefa registrada nesta sessão."}
                </Text>
              </View>

              {/* Coluna 2: justificativas */}
              <View
                style={[
                  local.analysisColumn,
                  individualColumns && {
                    flex: 1.15,
                    borderLeftWidth: 1,
                    borderColor: colors.line,
                    paddingLeft: 24,
                  },
                ]}
              >
                <Text style={s.text}>
                  Justificativas mais utilizadas
                </Text>

                {reasonCounts.map((item) => (
                  <View
                    key={item.reason}
                    style={{ gap: 8 }}
                  >
                    <Text style={s.muted}>
                      {item.reason} · {item.count}
                    </Text>

                    <View style={local.track}>
                      <BrandGradient
                        style={{
                          height: 7,
                          borderRadius: 4,
                          width: `${
                            (100 * item.count) /
                            Math.max(1, decisions.length)
                          }%`,
                        }}
                      />
                    </View>
                  </View>
                ))}

                {!reasonCounts.length && (
                  <Text style={s.empty}>
                    Nenhuma justificativa registrada por
                    este agente.
                  </Text>
                )}

                <Text style={s.muted}>
                  Frequência dos textos registrados nesta
                  sessão.
                </Text>
              </View>

              {/* Coluna 3: gráfico vertical */}
              <View
                style={[
                  local.analysisColumn,
                  individualColumns && {
                    flex: 1.3,
                    borderLeftWidth: 1,
                    borderColor: colors.line,
                    paddingLeft: 24,
                  },
                ]}
              >
                <Text style={s.text}>Comunicações</Text>

                <CommunicationChart
                  items={communicationCounts}
                />

                <Text style={s.muted}>
                  Mensagens enviadas pelo agente
                  selecionado para cada destinatário.
                </Text>
              </View>
            </View>
          </Card>

          <Text style={s.heading}>
            Análise por atendimento
          </Text>

          {sessionPicker}

          <Card>
            <View
              style={{
                flexDirection: wide ? "row" : "column",
                gap: 22,
              }}
            >
              <View style={{ flex: 1.4, gap: 12 }}>
                <Text style={s.heading}>
                  Comunicação entre agentes
                </Text>

                <View style={s.card}>
                  <AgentGraph
                    agents={agents}
                    events={events}
                  />
                </View>
              </View>

              <View style={{ flex: 1, gap: 12 }}>
                <Text style={s.heading}>
                  Histórico de comunicação
                </Text>

                <ScrollView
                  style={[s.card, { maxHeight: 450 }]}
                  contentContainerStyle={{
                    gap: 20,
                    paddingBottom: 18,
                  }}
                >
                  {communications.map((event) => (
                    <View
                      key={event.event_id}
                      style={local.timelineItem}
                    >
                      <Text style={s.text}>
                        {agentName(event.actor.id)}
                        {" → "}
                        {agentName(event.recipient!.id)}
                      </Text>

                      <Text style={s.muted}>
                        {event.payload.summary}
                      </Text>

                      <Text style={s.muted}>
                        {new Date(
                          event.occurred_at,
                        ).toLocaleTimeString("pt-BR")}
                      </Text>
                    </View>
                  ))}

                  {!communications.length && (
                    <Text style={s.empty}>
                      Sem comunicações registradas.
                    </Text>
                  )}
                </ScrollView>
              </View>
            </View>

            <View style={[s.row, { paddingTop: 20 }]}>
              <View
                style={{
                  flex: 1,
                  minWidth: 220,
                  gap: 12,
                }}
              >
                <Text style={s.heading}>
                  Interação com o usuário
                </Text>

                <Card>
                  {snapshot?.messages.map((message) => (
                    <View
                      key={message.message_id}
                      style={local.timelineItem}
                    >
                      <Text style={s.text}>
                        {message.role === "customer"
                          ? "Usuário"
                          : "PedIA"}
                      </Text>

                      <Text style={s.muted}>
                        {message.text}
                      </Text>
                    </View>
                  ))}

                  {!snapshot?.messages.length && (
                    <Text style={s.empty}>
                      Nenhuma mensagem registrada.
                    </Text>
                  )}
                </Card>
              </View>

              <View
                style={{
                  flex: 1.3,
                  minWidth: 250,
                  gap: 12,
                }}
              >
                <Text style={s.heading}>
                  Pedido recomendado
                </Text>

                {snapshot?.recommendations.map(
                  (recommendation) => (
                    <Offer
                      key={
                        recommendation.recommendation_id
                      }
                      offer={recommendation}
                    />
                  ),
                )}
              </View>

              <View
                style={{
                  flex: 1,
                  minWidth: 180,
                  gap: 12,
                }}
              >
                <Text style={s.heading}>
                  Dados gerais
                </Text>

                <Metric
                  label="Total do carrinho"
                  value={money(
                    snapshot?.cart?.total_cents,
                  )}
                />

                <Metric
                  label="Decisões do agente"
                  value={decisions.length}
                />
              </View>
            </View>
          </Card>

          <Card title="Decisões, fontes e atividade">
            {auditEvents.map((event) => (
              <View
                key={event.event_id}
                style={local.timelineItem}
              >
                <Badge text={event.type} />

                <Text style={s.text}>
                  {agentName(event.actor.id)}
                </Text>

                <Text
                  style={
                    event.type === "error"
                      ? s.error
                      : s.muted
                  }
                >
                  {eventDescription(event)}
                </Text>
              </View>
            ))}

            {!auditEvents.length && (
              <Text style={s.empty}>
                Nenhuma atividade registrada.
              </Text>
            )}
          </Card>
        </>
      )}
    </ScrollView>
  );
}

const local = StyleSheet.create({
  // Padding dos cards dos agentes.
  agentCard: {
    paddingVertical: 16,
    paddingHorizontal: 16,
    gap: 14,
  },

  agentCardHorizontal: {
    flexDirection: "row",
    alignItems: "center",
  },

  agentCardVertical: {
    flexGrow: 1,
    flexBasis: 190,
    minWidth: 180,
    alignItems: "flex-start",
  },

  selectedCard: {
    borderColor: "#FF969D",
    backgroundColor: "#FFF8F8",
  },

  status: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    flexShrink: 0,
  },

  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },

  conflictContent: {
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
  },

  conflictFooter: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 10,
  },

  sessionPill: {
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 9,
    backgroundColor: "#FFFFFF",
  },

  timelineItem: {
    borderLeftWidth: 2,
    borderColor: "#DDDDDD",
    paddingLeft: 14,
    paddingVertical: 8,
    gap: 8,
  },

  analysisColumn: {
    gap: 16,
    minWidth: 0,
  },

  track: {
    height: 7,
    borderRadius: 4,
    backgroundColor: "#E5E5E5",
    overflow: "hidden",
  },

  // Estilos do gráfico de comunicações.
  chartContainer: {
    width: "100%",
    minWidth: 0,
  },

  chartScroll: {
    flexGrow: 1,
    paddingBottom: 8,
  },

  chart: {
    flexGrow: 1,
    minWidth: 380,
  },

  chartPlot: {
    height: 185,
    flexDirection: "row",
    alignItems: "flex-end",
    borderBottomWidth: 1,
    borderBottomColor: "#E5E5E5",
  },

  chartColumn: {
    flex: 1,
    minWidth: 76,
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 8,
  },

  chartValue: {
    fontFamily: "InterMedium",
    fontSize: 15,
    lineHeight: 22,
    color: colors.ink,
  },

  chartBar: {
    width: 30,
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
  },

  chartLabels: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingTop: 10,
  },

  chartLabelColumn: {
    flex: 1,
    minWidth: 76,
    paddingHorizontal: 4,
  },

  chartLabel: {
    fontFamily: "Inter",
    fontSize: 15,
    lineHeight: 21,
    textAlign: "center",
    color: colors.muted,
  },
});