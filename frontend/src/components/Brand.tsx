import React from "react";
import {
  View,
  Text,
  StyleProp,
  ViewStyle,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Svg, { Path } from "react-native-svg";
import { FontAwesomeIcon } from "@fortawesome/react-native-fontawesome";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";

import { faSitemap } from "@fortawesome/free-solid-svg-icons/faSitemap";
import { faMagnifyingGlass } from "@fortawesome/free-solid-svg-icons/faMagnifyingGlass";
import { faFileLines } from "@fortawesome/free-solid-svg-icons/faFileLines";
import { faChessKnight } from "@fortawesome/free-solid-svg-icons/faChessKnight";
import { faTag } from "@fortawesome/free-solid-svg-icons/faTag";
import { faClipboardCheck } from "@fortawesome/free-solid-svg-icons/faClipboardCheck";
import { faRobot } from "@fortawesome/free-solid-svg-icons/faRobot";
import { faMicrophone } from "@fortawesome/free-solid-svg-icons/faMicrophone";
import { faPaperPlane } from "@fortawesome/free-solid-svg-icons/faPaperPlane";
import { faArrowLeft } from "@fortawesome/free-solid-svg-icons/faArrowLeft";
import { faEllipsisVertical } from "@fortawesome/free-solid-svg-icons/faEllipsisVertical";

// Para trocar o ícone de um agente, altere este mapa.
export const agentIcons: Record<string, IconDefinition> = {
  orchestrator: faSitemap,
  researcher: faMagnifyingGlass,
  planner: faFileLines,
  strategist: faChessKnight,
  discount_specialist: faTag,
  auditor: faClipboardCheck,
};

const interfaceIcons: Record<string, IconDefinition> = {
  search: faMagnifyingGlass,
  network: faSitemap,
  file: faFileLines,
  strategy: faChessKnight,
  discount: faTag,
  check: faClipboardCheck,
  mic: faMicrophone,
  send: faPaperPlane,
  back: faArrowLeft,
  more: faEllipsisVertical,
  agent: faRobot,
};

export const getAgentIcon = (id: string): IconDefinition =>
  agentIcons[id] ?? faRobot;

export const brandGradient = ["#FF575E", "#FF0000"] as const;

export function BrandGradient({
  children,
  style,
}: {
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <LinearGradient
      colors={brandGradient}
      start={{ x: 0, y: 0 }}
      end={{ x: 0.45, y: 1 }}
      style={style}
    >
      {children}
    </LinearGradient>
  );
}

export function Icon({
  name = "agent",
  size = 22,
  color = "#FFFFFF",
}: {
  name?: string;
  size?: number;
  color?: string;
}) {
  const icon =
    agentIcons[name] ??
    interfaceIcons[name] ??
    faRobot;

  return (
    <FontAwesomeIcon
      icon={icon}
      size={size}
      color={color}
    />
  );
}

export function AgentIcon({
  id,
  size = 42,
}: {
  id: string;
  size?: number;
}) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: 9,
        backgroundColor: "#FF545C",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <FontAwesomeIcon
        icon={getAgentIcon(id)}
        size={size * 0.58}
        color="#FFFFFF"
      />
    </View>
  );
}

export function Wordmark() {
  return (
    <View
      accessibilityLabel="iFood"
      style={{ alignSelf: "flex-start" }}
    >
      <Text
        style={{
          fontFamily: "InterBold",
          fontSize: 34,
          letterSpacing: -2,
          fontStyle: "italic",
          color: "#FFFFFF",
        }}
      >
        ifood
      </Text>

      <Svg width={43} height={11} viewBox="0 0 43 11">
        <Path
          d="M8 1c6 7 17 8 27 1l-2 7 8-9"
          fill="none"
          stroke="#FFFFFF"
          strokeWidth={2.2}
        />
      </Svg>
    </View>
  );
}