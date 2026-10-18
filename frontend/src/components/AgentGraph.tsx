import React from "react";
import { View } from "react-native";
import Svg, {
  Path,
  Rect,
  Circle,
  Text as SvgText,
} from "react-native-svg";
import { getAgentIcon } from "./Brand";
import type {
  AgentDefinition,
  OfficeEvent,
} from "../types/api";

export function AgentGraph({
  agents,
  events,
}: {
  agents: AgentDefinition[];
  events: OfficeEvent[];
}) {
  const positions = new Map(
    agents.map((agent, index) => {
      const angle =
        (index * 2 * Math.PI) / Math.max(1, agents.length) -
        Math.PI / 2;

      return [
        agent.agent_id,
        {
          x: 300 + 190 * Math.cos(angle),
          y: 220 + 155 * Math.sin(angle),
        },
      ];
    }),
  );

  const connections = new Map<
    string,
    { from: string; to: string }
  >();

  for (const event of events) {
    if (event.type !== "agent_message" || !event.recipient) {
      continue;
    }

    const key = `${event.actor.id}>${event.recipient.id}`;

    connections.set(key, {
      from: event.actor.id,
      to: event.recipient.id,
    });
  }

  return (
    <View style={{ width: "100%", height: 400 }}>
      <Svg
        width="100%"
        height="100%"
        viewBox="0 0 600 440"
        accessibilityLabel="Comunicação entre agentes"
      >
        {[...connections.entries()].map(([key, connection]) => {
          const from = positions.get(connection.from);
          const to = positions.get(connection.to);

          if (!from || !to) return null;

          return (
            <Path
              key={key}
              d={`M ${from.x} ${from.y} Q 300 220 ${to.x} ${to.y}`}
              fill="none"
              stroke="#FF343E"
              strokeWidth={1.5}
            />
          );
        })}

        {agents.map((agent) => {
          const position = positions.get(agent.agent_id)!;
          const icon = getAgentIcon(agent.agent_id);
          const paths = Array.isArray(icon.icon[4])
            ? icon.icon[4]
            : [icon.icon[4]];

          const lastStatus = events
            .filter(
              (event) =>
                event.type === "agent_status" &&
                event.payload.agent_id === agent.agent_id,
            )
            .at(-1);

          const status =
            lastStatus?.type === "agent_status"
              ? lastStatus.payload.status
              : "Sem atividade";

          const label =
            agent.name.length > 16
              ? `${agent.name.slice(0, 15)}…`
              : agent.name;

          return (
            <React.Fragment key={agent.agent_id}>
              <Rect
                x={position.x - 82}
                y={position.y - 33}
                width={164}
                height={68}
                rx={9}
                fill="#FFFFFF"
                stroke="#E6E6E6"
              />

              <Rect
                x={position.x - 72}
                y={position.y - 23}
                width={28}
                height={28}
                rx={6}
                fill="#FF545C"
              />

              <Svg
                x={position.x - 67}
                y={position.y - 18}
                width={18}
                height={18}
                viewBox={`0 0 ${icon.icon[0]} ${icon.icon[1]}`}
              >
                {paths.map((path, index) => (
                  <Path
                    key={index}
                    d={path}
                    fill="#FFFFFF"
                  />
                ))}
              </Svg>

              <SvgText
                x={position.x - 36}
                y={position.y - 5}
                fontFamily="Inter"
                fontSize={12}
                fill="#373737"
              >
                {label}
              </SvgText>

              <SvgText
                x={position.x - 71}
                y={position.y + 23}
                fontFamily="Inter"
                fontSize={11}
                fill="#737373"
              >
                {status}
              </SvgText>

              <Circle
                cx={position.x + 68}
                cy={position.y + 20}
                r={3}
                fill={
                  status === "error"
                    ? "#FF454E"
                    : status === "Sem atividade"
                      ? "#CCCCCC"
                      : "#95EF80"
                }
              />
            </React.Fragment>
          );
        })}
      </Svg>
    </View>
  );
}