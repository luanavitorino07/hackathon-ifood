import React from "react";
import { View } from "react-native";
import Svg, { Circle, G, Path, Rect, Text as SvgText } from "react-native-svg";
import { getAgentIcon } from "./Brand";
import { agentStatusLabel } from "../theme";
import type { AgentDefinition, OfficeEvent } from "../types/api";

const W = 820;
const H = 560;
const CX = W / 2;
const CY = H / 2;
const NODE_W = 176;
const NODE_H = 62;
const HUB = "orchestrator";

const statusColor: Record<string, string> = {
  running: "#FF9D20",
  waiting: "#2F6FDE",
  done: "#13A538",
  error: "#FF454E",
};

export function AgentGraph({ agents, events }: { agents: AgentDefinition[]; events: OfficeEvent[] }) {
  // Orquestrador no centro; os demais em elipse ao redor, sem sobreposição.
  const ring = agents.filter((a) => a.agent_id !== HUB);
  const positions = new Map<string, { x: number; y: number }>();
  if (agents.some((a) => a.agent_id === HUB)) positions.set(HUB, { x: CX, y: CY });
  ring.forEach((agent, index) => {
    const angle = (index * 2 * Math.PI) / Math.max(1, ring.length) - Math.PI / 2;
    positions.set(agent.agent_id, { x: CX + 300 * Math.cos(angle), y: CY + 210 * Math.sin(angle) });
  });

  // Arestas não direcionadas, com contagem de mensagens.
  const edges = new Map<string, { a: string; b: string; count: number }>();
  for (const event of events) {
    if (event.type !== "agent_message" || !event.recipient) continue;
    const [a, b] = [event.actor.id, event.recipient.id].sort();
    const key = `${a}|${b}`;
    const edge = edges.get(key) ?? { a, b, count: 0 };
    edge.count++;
    edges.set(key, edge);
  }
  const maxCount = Math.max(1, ...[...edges.values()].map((e) => e.count));

  const lastStatus = (id: string) => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.type === "agent_status" && e.payload.agent_id === id) return e.payload.status;
    }
    return null;
  };

  return (
    <View style={{ width: "100%", aspectRatio: W / H, maxHeight: 520 }}>
      <Svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} accessibilityLabel="Comunicação entre agentes">
        {[...edges.values()].map((edge) => {
          const from = positions.get(edge.a);
          const to = positions.get(edge.b);
          if (!from || !to) return null;
          const touchesHub = edge.a === HUB || edge.b === HUB;
          // Arestas entre especialistas fazem curva por fora do centro.
          const mx = (from.x + to.x) / 2;
          const my = (from.y + to.y) / 2;
          const bend = touchesHub ? 0 : 0.35;
          const qx = mx + (mx - CX) * bend;
          const qy = my + (my - CY) * bend;
          const width = 1.5 + (3.5 * edge.count) / maxCount;
          return (
            <G key={`${edge.a}|${edge.b}`}>
              <Path
                d={`M ${from.x} ${from.y} Q ${qx} ${qy} ${to.x} ${to.y}`}
                fill="none"
                stroke={touchesHub ? "#FF8A90" : "#FF343E"}
                strokeWidth={width}
                strokeDasharray={touchesHub ? undefined : "6 4"}
                opacity={0.85}
              />
              <Circle cx={(mx + qx) / 2} cy={(my + qy) / 2} r={11} fill="#FFFFFF" stroke="#FFB3B7" />
              <SvgText x={(mx + qx) / 2} y={(my + qy) / 2 + 4} fontSize={11} fontFamily="Inter" fill="#C6202C" textAnchor="middle">
                {String(edge.count)}
              </SvgText>
            </G>
          );
        })}

        {agents.map((agent) => {
          const p = positions.get(agent.agent_id);
          if (!p) return null;
          const icon = getAgentIcon(agent.agent_id);
          const paths = Array.isArray(icon.icon[4]) ? icon.icon[4] : [icon.icon[4]];
          const status = lastStatus(agent.agent_id);
          const hub = agent.agent_id === HUB;
          const label = agent.name.length > 19 ? `${agent.name.slice(0, 18)}…` : agent.name;
          const color = status ? statusColor[status] ?? "#CCCCCC" : "#CCCCCC";
          return (
            <G key={agent.agent_id}>
              <Rect
                x={p.x - NODE_W / 2}
                y={p.y - NODE_H / 2}
                width={NODE_W}
                height={NODE_H}
                rx={12}
                fill={hub ? "#FFF0F1" : "#FFFFFF"}
                stroke={status === "running" ? "#FF9D20" : hub ? "#FFB3B7" : "#E6E6E6"}
                strokeWidth={status === "running" ? 2.5 : 1}
              />
              <Rect x={p.x - NODE_W / 2 + 10} y={p.y - 17} width={34} height={34} rx={8} fill="#FF545C" />
              <Svg
                x={p.x - NODE_W / 2 + 17}
                y={p.y - 10}
                width={20}
                height={20}
                viewBox={`0 0 ${icon.icon[0]} ${icon.icon[1]}`}
              >
                {paths.map((path, index) => (
                  <Path key={index} d={path} fill="#FFFFFF" />
                ))}
              </Svg>
              <SvgText x={p.x - NODE_W / 2 + 52} y={p.y - 3} fontFamily="Inter" fontSize={13} fill="#373737" fontWeight={hub ? "700" : "500"}>
                {label}
              </SvgText>
              <Circle cx={p.x - NODE_W / 2 + 56} cy={p.y + 14} r={4} fill={color} />
              <SvgText x={p.x - NODE_W / 2 + 65} y={p.y + 18} fontFamily="Inter" fontSize={11.5} fill="#737373">
                {status ? agentStatusLabel[status] ?? status : "Sem atividade"}
              </SvgText>
            </G>
          );
        })}
      </Svg>
    </View>
  );
}
