import React, { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, ScrollView, Text, View, useWindowDimensions } from "react-native";
import { api } from "../services/api";
import { computeExecutive, type SessionHistory } from "../services/executive";
import { BarList, Card, Pill, StatCard } from "../components/ui";
import { BrandGradient, Icon } from "../components/Brand";
import { colors, money, percent, relativeTime, styles as s } from "../theme";
import type { AdminOverviewResponse, AgentDefinition, OfficeEvent } from "../types/api";

const client = api(true);
const REFRESH_MS = 6000;

function useExecutiveData() {
  const [overview, setOverview] = useState<AdminOverviewResponse | null>(null);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [histories, setHistories] = useState<SessionHistory[]>([]);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const cache = useRef(new Map<string, { seq: number; events: OfficeEvent[] }>());

  useEffect(() => {
    let alive = true;
    let busy = false;
    async function load() {
      if (busy) return;
      busy = true;
      try {
        const [next, catalog] = await Promise.all([client.overview(), client.catalog()]);
        const sessions = next.recent_sessions.filter((r) => r.last_seq > 1);
        const loaded = await Promise.all(
          sessions.map(async (r) => {
            const hit = cache.current.get(r.session_id);
            if (hit && hit.seq === r.last_seq) return { r, events: hit.events };
            const events: OfficeEvent[] = hit ? [...hit.events] : [];
            let cursor = hit?.seq ?? 0;
            for (let page = 0; page < 10; page++) {
              const h = await client.history(r.session_id, cursor);
              events.push(...h.events);
              cursor = h.last_seq;
              if (!h.has_more) break;
            }
            cache.current.set(r.session_id, { seq: r.last_seq, events });
            return { r, events };
          }),
        );
        if (!alive) return;
        setOverview(next);
        setAgents(catalog.agents);
        setHistories(
          loaded.map(({ r, events }) => ({
            session_id: r.session_id,
            client_alias: r.client_alias,
            status: r.status,
            updated_at: r.updated_at,
            events,
          })),
        );
        setUpdatedAt(new Date());
        setError("");
      } catch (e) {
        if (alive) setError(String(e));
      } finally {
        busy = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  return { overview, agents, histories, error, updatedAt };
}

function seconds(ms: number | null) {
  if (ms == null) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function Funnel({ steps }: { steps: { label: string; value: number }[] }) {
  const max = Math.max(1, steps[0]?.value ?? 1);
  return (
    <View style={{ gap: 12 }}>
      {steps.map((step, index) => {
        const prev = index ? steps[index - 1].value : null;
        return (
          <View key={step.label} style={{ gap: 6 }}>
            <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8 }}>
              <Text style={[s.text, { flex: 1, fontSize: 15, lineHeight: 21 }]}>{step.label}</Text>
              <Text style={[s.text, { fontFamily: "InterSemiBold", fontSize: 15 }]}>{step.value}</Text>
              {prev != null && (
                <Text style={[s.muted, { fontSize: 13, width: 44, textAlign: "right" }]}>
                  {percent(prev ? step.value / prev : null)}
                </Text>
              )}
            </View>
            <View style={{ height: 14, borderRadius: 7, backgroundColor: "#F1F1F1", overflow: "hidden" }}>
              <BrandGradient
                style={{ height: 14, borderRadius: 7, width: `${Math.max(step.value ? 4 : 0, (100 * step.value) / max)}%` }}
              />
            </View>
          </View>
        );
      })}
    </View>
  );
}

function Row({ children, wide }: { children: React.ReactNode; wide: boolean }) {
  return (
    <View style={{ flexDirection: wide ? "row" : "column", gap: 18, alignItems: "stretch" }}>{children}</View>
  );
}

function Col({ children, flex = 1 }: { children: React.ReactNode; flex?: number }) {
  return <View style={{ flex, minWidth: 0, gap: 18 }}>{children}</View>;
}

export function CeoScreen() {
  const width = useWindowDimensions().width;
  const wide = width >= 1100;
  const { overview, agents, histories, error, updatedAt } = useExecutiveData();
  const name = (id: string) => agents.find((a) => a.agent_id === id)?.name ?? id;
  const x = useMemo(() => computeExecutive(histories, name), [histories, agents]);
  const sessions = overview?.metrics.sessions_started ?? x.sessions;
  const aiRate = x.aiCalls ? x.aiSucceeded / x.aiCalls : null;
  const quota = x.aiFailureReasons.find((r) => r.label.includes("cota"));

  return (
    <ScrollView style={s.page} contentContainerStyle={[s.content, { padding: wide ? 32 : 18, gap: 22 }]}>
      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <View style={{ flex: 1, minWidth: 240, gap: 4 }}>
          <Text style={s.title}>Visão do CEO</Text>
          <Text style={s.muted}>
            Resultados da PedIA nas últimas 24 h · calculados a partir dos eventos reais dos atendimentos
          </Text>
        </View>
        {overview && (
          <Pill
            text={overview.mode === "demo" ? "Dados de demonstração" : "Dados reais (iFood)"}
            tone={overview.mode === "demo" ? "amber" : "green"}
          />
        )}
        {updatedAt && <Text style={[s.muted, { fontSize: 13 }]}>Atualizado {relativeTime(updatedAt.toISOString())}</Text>}
      </View>

      {!!error && (
        <Text accessibilityRole="alert" style={s.error}>
          {error}
        </Text>
      )}
      {!overview && !error && <ActivityIndicator color={colors.red} />}

      {!!quota && (
        <View style={[s.card, { backgroundColor: colors.amberSoft, borderColor: "#FFD48A", flexDirection: "row", gap: 12, alignItems: "center" }]}>
          <Icon name="warning" color={colors.amber} size={20} />
          <Text style={[s.text, { flex: 1, fontSize: 15, lineHeight: 22 }]}>
            A IA ficou sem cota em {quota.value} consulta(s). Nesses casos os agentes usaram as regras de reserva — o
            atendimento continua, mas sem o julgamento da IA. Troque a chave ou o modelo para reativar.
          </Text>
        </View>
      )}

      <View style={s.row}>
        <StatCard icon="users" label="Atendimentos" value={sessions} hint={`${x.withOrderIntent} com pedido de comida`} />
        <StatCard icon="ok" label="Taxa de recomendação" value={percent(x.recommendationRate)} hint="pedidos que receberam uma opção" tone="green" />
        <StatCard icon="money" label="Ticket médio recomendado" value={money(x.averageTicketCents)} hint="recomendação principal" />
        <StatCard icon="chart" label="Valor recomendado" value={money(x.recommendedValueCents)} hint="soma das recomendações principais" tone="blue" />
        <StatCard icon="clock" label="Tempo médio de resposta" value={seconds(x.averageResponseMs)} hint="da mensagem do cliente à resposta" tone="amber" />
      </View>

      <Row wide={wide}>
        <Col>
          <Card title="Funil de atendimento">
            <Funnel
              steps={[
                { label: "Atendimentos", value: sessions },
                { label: "Pediram comida", value: x.withOrderIntent },
                { label: "Receberam recomendação", value: x.withRecommendation },
                { label: "Enviaram pedido", value: x.ordersSubmitted },
              ]}
            />
          </Card>
          <Card title="Inteligência artificial" right={<Pill text={`${percent(aiRate)} de sucesso`} tone={aiRate == null ? "gray" : aiRate >= 0.8 ? "green" : "amber"} />}>
            <Text style={s.muted}>
              {x.aiCalls} consulta(s) à IA pelos agentes · {x.curatorRejections} julgamento(s) do Curador descartaram itens fora do pedido
            </Text>
            <BarList items={x.aiByAgent} empty="Nenhuma consulta à IA ainda." />
            {x.aiFailureReasons.length > 0 && (
              <View style={{ gap: 6 }}>
                <Text style={[s.text, { fontSize: 15 }]}>Motivos de falha</Text>
                {x.aiFailureReasons.map((r) => (
                  <Text key={r.label} style={[s.muted, { color: colors.amber }]}>
                    ⚠ {r.label} · {r.value}
                  </Text>
                ))}
              </View>
            )}
          </Card>
        </Col>
        <Col>
          <Card title="Buscas no iFood">
            <View style={s.row}>
              <StatCard icon="search" label="Buscas feitas" value={x.searches} hint={`${x.searchesSucceeded} com sucesso`} />
              <StatCard icon="bolt" label="Buscas economizadas" value={x.reusedSearches} hint="retomada sem nova busca" tone="green" />
            </View>
            <Text style={s.muted}>
              {x.realSearches} busca(s) no MCP real do iFood. A retomada reaproveita a pesquisa quando o cliente só muda quantidade ou orçamento, economizando cota.
            </Text>
          </Card>
          <Card title="Comercial">
            <View style={s.row}>
              <StatCard icon="discount" label="Descontos sugeridos" value={x.discountsSuggested} hint={`${money(x.discountSuggestedCents)} no total`} />
              <StatCard icon="trophy" label="Lucro esperado (estimativa)" value={money(x.profitDeltaCents)} hint="hipóteses da política DEMO" tone="green" />
            </View>
            <Text style={s.muted}>
              Descontos são só sugestões ao gestor: nunca são aplicados nem mostrados ao cliente. Conflitos entre agentes: {x.conflictsOpen} aberto(s), {x.conflictsResolved} resolvido(s).
            </Text>
          </Card>
        </Col>
      </Row>

      <Row wide={wide}>
        <Col>
          <Card title="Pratos mais pedidos">
            <BarList items={x.topDishes} empty="Ainda sem pedidos com prato identificado." format={(n) => `${n}×`} />
          </Card>
        </Col>
        <Col>
          <Card title="Restaurantes mais recomendados">
            <BarList items={x.topMerchants} empty="Ainda sem recomendações." format={(n) => `${n}×`} />
          </Card>
        </Col>
      </Row>

      <Row wide={wide}>
        <Col flex={1.2}>
          <Card title="Decisões recentes">
            {x.decisions.length === 0 && <Text style={s.empty}>Nenhuma decisão registrada.</Text>}
            {x.decisions.map((d) => (
              <View key={d.session + d.at} style={{ flexDirection: "row", gap: 12, paddingVertical: 6, borderBottomWidth: 1, borderColor: colors.line }}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[s.text, { fontSize: 15, lineHeight: 21 }]}>{d.summary}</Text>
                  <Text style={[s.muted, { fontSize: 13 }]}>
                    {d.alias} · {relativeTime(d.at)}
                  </Text>
                </View>
                {d.recommended ? (
                  <Text style={[s.text, { fontFamily: "InterSemiBold", fontSize: 15 }]}>{money(d.total)}</Text>
                ) : (
                  <Pill text="sem opção" tone="gray" />
                )}
              </View>
            ))}
          </Card>
        </Col>
        <Col>
          <Card title="Destaques da IA">
            {x.highlights.length === 0 && (
              <Text style={s.empty}>Quando a IA julgar ofertas ou escolher a melhor opção, os motivos aparecem aqui.</Text>
            )}
            {x.highlights.map((h) => (
              <View key={h.session + h.at + h.agent} style={{ gap: 2, paddingVertical: 6, borderBottomWidth: 1, borderColor: colors.line }}>
                <Text style={[s.text, { fontSize: 15, lineHeight: 21, fontFamily: "InterMedium" }]}>{h.agent}</Text>
                <Text style={[s.muted, { fontSize: 14 }]}>{h.text}</Text>
                <Text style={[s.muted, { fontSize: 12 }]}>
                  {h.alias} · {relativeTime(h.at)}
                </Text>
              </View>
            ))}
          </Card>
        </Col>
      </Row>
    </ScrollView>
  );
}
