// Indicadores executivos calculados a partir dos eventos reais de cada atendimento
// (histórico do gestor). Nada é inventado: sem dado, o valor fica null.
import type { OfficeEvent, Recommendation } from "../types/api";

export type SessionHistory = {
  session_id: string;
  client_alias: string;
  status: string;
  updated_at: string;
  events: OfficeEvent[];
};

export type Ranked = { label: string; value: number; note?: string };
export type StrategyStat = { name: string; offered: number; accepted: number; rate: number | null };

export type Executive = {
  sessions: number;
  withOrderIntent: number; // atendimentos em que o cliente pediu comida
  withRecommendation: number;
  ordersSubmitted: number;
  salesClosed: number; // cliente aceitou a recomendação no chat
  strategies: StrategyStat[]; // histórico da memória (inclui clientes fictícios) + atendimentos depois dele
  recommendationRate: number | null;
  averageTicketCents: number | null; // total da recomendação principal
  recommendedValueCents: number;
  averageResponseMs: number | null;
  aiCalls: number;
  aiSucceeded: number;
  aiFailureReasons: Ranked[];
  aiByAgent: Ranked[];
  searches: number;
  searchesSucceeded: number;
  realSearches: number; // provider ifood_mcp
  reusedSearches: number; // retomada sem nova busca
  discountsSuggested: number;
  discountSuggestedCents: number;
  profitDeltaCents: number;
  conflictsOpen: number;
  conflictsResolved: number;
  curatorRejections: number;
  topDishes: Ranked[];
  topMerchants: Ranked[];
  decisions: { session: string; alias: string; at: string; summary: string; total: number | null; recommended: boolean }[];
  highlights: { session: string; alias: string; at: string; agent: string; text: string }[];
};

const mean = (values: number[]) =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;

function rank(counts: Map<string, number>, limit = 5): Ranked[] {
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([label, value]) => ({ label, value }));
}

const bump = (map: Map<string, number>, key: string, by = 1) =>
  map.set(key, (map.get(key) ?? 0) + by);

const FAILURE = /^(.*?);\s*regra de reserva usada/;
const PERFORMANCE = "Desempenho das estratégias:";
const APPLIED = /^Estratégia aplicada:\s*(.+?)\s+—\s*(.*)$/;
const SOLD = /^Venda fechada:.*\(estratégia:\s*(.+)\)$/;

function parsePerformance(summary: string) {
  const out = new Map<string, { offered: number; accepted: number }>();
  for (const part of summary.slice(PERFORMANCE.length).split(";")) {
    const m = /^\s*(.+?)\s+(\d+)\/(\d+)\s*$/.exec(part);
    if (m) out.set(m[1], { accepted: Number(m[2]), offered: Number(m[3]) });
  }
  return out;
}

export function computeExecutive(
  histories: SessionHistory[],
  agentName: (id: string) => string = (id) => id,
): Executive {
  const dishes = new Map<string, number>();
  const merchants = new Map<string, number>();
  const failures = new Map<string, number>();
  const aiAgents = new Map<string, number>();
  const tickets: number[] = [];
  const responses: number[] = [];
  const decisions: Executive["decisions"] = [];
  const highlights: Executive["highlights"] = [];
  const conflicts = new Map<string, string>();
  let baseline: { at: string; stats: Map<string, { offered: number; accepted: number }> } | null = null;
  const applied: { at: string; name: string }[] = [];
  const sold: { at: string; name: string }[] = [];
  let withOrderIntent = 0,
    withRecommendation = 0,
    ordersSubmitted = 0,
    recommendedValue = 0,
    aiCalls = 0,
    aiOk = 0,
    searches = 0,
    searchesOk = 0,
    realSearches = 0,
    reused = 0,
    discounts = 0,
    discountCents = 0,
    profitDelta = 0,
    curatorRejections = 0;

  for (const h of histories) {
    let lastCustomerAt: number | null = null;
    let latest: Recommendation[] | null = null;
    let ordered = false;
    for (const e of h.events) {
      const at = new Date(e.occurred_at).getTime();
      switch (e.type) {
        case "chat_message":
          if (e.payload.message.role === "customer") lastCustomerAt = at;
          else if (lastCustomerAt != null) {
            responses.push(at - lastCustomerAt);
            lastCustomerAt = null;
          }
          break;
        case "agent_message": {
          const summary = e.payload.summary;
          if (summary.startsWith(PERFORMANCE) && (!baseline || e.occurred_at > baseline.at))
            baseline = { at: e.occurred_at, stats: parsePerformance(summary) };
          const ap = APPLIED.exec(summary);
          if (ap && e.actor.id === "sales_strategist") applied.push({ at: e.occurred_at, name: ap[1] });
          const so = SOLD.exec(summary);
          if (so) sold.push({ at: e.occurred_at, name: so[1] });
        }
          if (e.actor.id === "researcher" && e.recipient?.id === "orchestrator") ordered = true;
          if (e.payload.summary.startsWith("Pesquisa reaproveitada")) {
            reused++;
            ordered = true;
          }
          if (e.actor.id === "curator") {
            const m = /descartados?, ex\.: (.*)\.$/.exec(e.payload.summary);
            if (m) {
              curatorRejections++;
              highlights.push({ session: h.session_id, alias: h.client_alias, at: e.occurred_at, agent: "Curador (IA)", text: `Descartou ${m[1]}` });
            }
          }
          if (e.actor.id === "sales_strategist" && APPLIED.test(e.payload.summary))
            highlights.push({ session: h.session_id, alias: h.client_alias, at: e.occurred_at, agent: "Estrategista (IA)", text: e.payload.summary.replace(/^Estratégia aplicada:\s*/, "").replace(/\s*\(conforme .*\)\s*$/, "") });
          if (e.actor.id === "curator" && e.recipient?.id === "researcher")
            highlights.push({ session: h.session_id, alias: h.client_alias, at: e.occurred_at, agent: "Curador → Pesquisador", text: e.payload.summary });
          break;
        case "tool_activity":
          if (e.payload.status === "started") break;
          if (e.payload.tool_name === "raciocinio_ia") {
            aiCalls++;
            bump(aiAgents, agentName(e.recipient?.id ?? "?"));
            if (e.payload.status === "succeeded") aiOk++;
            else bump(failures, FAILURE.exec(e.payload.summary)?.[1] ?? "falha da IA");
          } else {
            searches++;
            if (e.payload.status === "succeeded") searchesOk++;
            if (e.payload.provider === "ifood_mcp") realSearches++;
          }
          break;
        case "recommendations_ready":
          latest = e.payload.recommendations;
          break;
        case "discount_proposed":
          discounts++;
          discountCents += e.payload.discount_cents ?? 0;
          profitDelta += e.payload.estimated_profit_delta_cents ?? 0;
          break;
        case "conflict_detected":
          conflicts.set(e.payload.conflict_id, e.payload.status);
          break;
        case "memory_changed": {
          const m = /histórico do cliente:\s*(.+)$/.exec(e.payload.summary);
          if (m) bump(dishes, m[1].trim());
          break;
        }
        case "decision_made":
          decisions.push({
            session: h.session_id,
            alias: h.client_alias,
            at: e.occurred_at,
            summary: e.payload.summary.replace(/^Recomendação principal:\s*/, ""),
            recommended: e.payload.recommendation_id != null,
            total: e.payload.recommendation_id != null ? (latest?.[0]?.total_cents ?? null) : null,
          });
          break;
        case "order_status_changed":
          if (e.payload.status === "submitted" || e.payload.status === "confirmed") ordersSubmitted++;
          break;
      }
    }
    if (ordered) withOrderIntent++;
    if (latest?.length) {
      withRecommendation++;
      const top = latest[0];
      bump(merchants, top.merchant_name);
      const value = top.total_cents ?? top.subtotal_cents;
      if (value != null) {
        tickets.push(value);
        recommendedValue += value;
      }
    }
  }

  const byTime = <T extends { at: string }>(list: T[]) =>
    list.sort((a, b) => b.at.localeCompare(a.at));
  const openConflicts = [...conflicts.values()].filter((s) => s === "open").length;
  // Monitoria: o último retrato da memória + o que aconteceu depois dele nesta tela.
  const strategyMap = new Map<string, { offered: number; accepted: number }>();
  const b = baseline as { at: string; stats: Map<string, { offered: number; accepted: number }> } | null;
  b?.stats.forEach((v, k) => strategyMap.set(k, { ...v }));
  const after = (list: { at: string; name: string }[]) => list.filter((x) => !b || x.at > b.at);
  for (const a of after(applied)) {
    const cur = strategyMap.get(a.name) ?? { offered: 0, accepted: 0 };
    strategyMap.set(a.name, { ...cur, offered: cur.offered + 1 });
  }
  for (const v of after(sold)) {
    const cur = strategyMap.get(v.name) ?? { offered: 0, accepted: 0 };
    strategyMap.set(v.name, { ...cur, accepted: cur.accepted + 1 });
  }
  const strategies = [...strategyMap.entries()]
    .map(([name, v]) => ({ name, ...v, rate: v.offered ? v.accepted / v.offered : null }))
    .sort((x, y) => (y.rate ?? -1) - (x.rate ?? -1) || y.offered - x.offered);

  return {
    sessions: histories.length,
    withOrderIntent,
    withRecommendation,
    ordersSubmitted,
    salesClosed: sold.length,
    strategies,
    recommendationRate: withOrderIntent ? withRecommendation / withOrderIntent : null,
    averageTicketCents: mean(tickets),
    recommendedValueCents: recommendedValue,
    averageResponseMs: mean(responses),
    aiCalls,
    aiSucceeded: aiOk,
    aiFailureReasons: rank(failures),
    aiByAgent: rank(aiAgents),
    searches,
    searchesSucceeded: searchesOk,
    realSearches,
    reusedSearches: reused,
    discountsSuggested: discounts,
    discountSuggestedCents: discountCents,
    profitDeltaCents: profitDelta,
    conflictsOpen: openConflicts,
    conflictsResolved: conflicts.size - openConflicts,
    curatorRejections,
    topDishes: rank(dishes),
    topMerchants: rank(merchants),
    decisions: byTime(decisions).slice(0, 8),
    highlights: byTime(highlights).slice(0, 6),
  };
}
