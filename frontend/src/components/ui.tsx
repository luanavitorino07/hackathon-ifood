import React from "react";
import { Image, Pressable, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { BrandGradient, Icon } from "./Brand";
import { colors, styles as s, money } from "../theme";
import type { Recommendation } from "../types/api";

export function Button({
  title,
  onPress,
  disabled = false,
  icon,
  variant = "primary",
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  icon?: string;
  variant?: "primary" | "ghost";
}) {
  const content = icon ? (
    <Icon name={icon} size={21} color={variant === "ghost" ? colors.red : "#FFFFFF"} />
  ) : (
    <Text style={[s.buttonText, variant === "ghost" && { color: colors.red }]}>{title}</Text>
  );
  const box = [
    s.button,
    icon ? { width: 48, height: 48, paddingHorizontal: 0, paddingVertical: 0 } : {},
  ];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        opacity: disabled ? 0.4 : pressed ? 0.75 : 1,
        borderRadius: 25,
        overflow: "hidden",
      })}
    >
      {variant === "ghost" ? (
        <View style={[box, { backgroundColor: colors.redSoft, borderWidth: 1, borderColor: "#FFD0D3" }]}>
          {content}
        </View>
      ) : (
        <BrandGradient style={box}>{content}</BrandGradient>
      )}
    </Pressable>
  );
}

export function Card({
  title,
  children,
  right,
}: {
  title?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <View style={s.card}>
      {!!(title || right) && (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          {!!title && <Text style={[s.heading, { flex: 1, fontSize: 19, lineHeight: 26 }]}>{title}</Text>}
          {right}
        </View>
      )}
      {children}
    </View>
  );
}

export function Metric({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <View style={[s.card, { flexGrow: 1, minWidth: 170 }]}>
      <Text style={s.metric}>{value}</Text>
      <Text style={s.muted}>{label}</Text>
    </View>
  );
}

type Tone = "red" | "green" | "amber" | "blue" | "gray";
const tones: Record<Tone, { fg: string; bg: string }> = {
  red: { fg: "#C6202C", bg: colors.redSoft },
  green: { fg: colors.green, bg: colors.greenSoft },
  amber: { fg: colors.amber, bg: colors.amberSoft },
  blue: { fg: colors.blue, bg: colors.blueSoft },
  gray: { fg: colors.muted, bg: "#F2F2F2" },
};

/** Etiqueta pequena com cor de status. */
export function Pill({ text, tone = "gray" }: { text: string; tone?: Tone }) {
  const t = tones[tone];
  return (
    <Text
      style={[
        s.badge,
        { backgroundColor: t.bg, color: t.fg, fontSize: 13, lineHeight: 18, paddingVertical: 3 },
      ]}
    >
      {text}
    </Text>
  );
}

export function Badge({ text }: { text: string }) {
  const status = text.toLowerCase();

  const isOpen = ["em aberto", "open"].includes(status);
  const isResolved = ["concluído", "resolved"].includes(status);

  if (isOpen || isResolved) {
    return (
      <LinearGradient
        colors={isOpen ? ["#FFCD72", "#FF9D20"] : ["#40D35D", "#0BA732"]}
        style={{
          alignSelf: "flex-start",
          paddingHorizontal: 16,
          paddingVertical: 5,
          borderRadius: 16,
        }}
      >
        <Text style={[s.muted, { color: "#FFFFFF", fontFamily: "InterMedium" }]}>{text}</Text>
      </LinearGradient>
    );
  }

  return <Text style={s.badge}>{text}</Text>;
}

/** Indicador grande com ícone, para a visão executiva. */
export function StatCard({
  icon,
  label,
  value,
  hint,
  tone = "red",
}: {
  icon: string;
  label: string;
  value: string | number;
  hint?: string;
  tone?: Tone;
}) {
  const t = tones[tone];
  return (
    <View style={[s.card, { flexGrow: 1, flexBasis: 150, minWidth: 150, gap: 10, padding: 16 }]}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            backgroundColor: t.bg,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Icon name={icon} size={17} color={t.fg} />
        </View>
        <Text style={[s.muted, { flex: 1, fontSize: 14, lineHeight: 19 }]}>{label}</Text>
      </View>
      <Text style={[s.metric, { fontSize: 28, lineHeight: 34 }]}>{value}</Text>
      {!!hint && <Text style={[s.muted, { fontSize: 13, lineHeight: 18 }]}>{hint}</Text>}
    </View>
  );
}

/** Ranking horizontal simples (sem biblioteca de gráficos). */
export function BarList({
  items,
  empty,
  format = (n) => String(n),
}: {
  items: { label: string; value: number; note?: string }[];
  empty: string;
  format?: (n: number) => string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <Text style={s.empty}>{empty}</Text>;
  return (
    <View style={{ gap: 14 }}>
      {items.map((item) => (
        <View key={item.label} style={{ gap: 6 }}>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Text style={[s.text, { flex: 1, fontSize: 15, lineHeight: 21 }]} numberOfLines={1}>
              {item.label}
            </Text>
            <Text style={[s.text, { fontSize: 15, lineHeight: 21, fontFamily: "InterSemiBold" }]}>
              {format(item.value)}
            </Text>
          </View>
          <View style={{ height: 8, borderRadius: 4, backgroundColor: "#F1F1F1", overflow: "hidden" }}>
            <BrandGradient style={{ height: 8, borderRadius: 4, width: `${(100 * item.value) / max}%` }} />
          </View>
          {!!item.note && <Text style={[s.muted, { fontSize: 13, lineHeight: 18 }]}>{item.note}</Text>}
        </View>
      ))}
    </View>
  );
}

function etaText(offer: Recommendation) {
  if (offer.eta_minutes == null) return "Prazo a confirmar";
  if (offer.eta_min_minutes != null && offer.eta_min_minutes < offer.eta_minutes)
    return `${offer.eta_min_minutes}–${offer.eta_minutes} min`;
  return `${offer.eta_minutes} min`;
}

export function Offer({
  offer,
  onSelect,
  highlight = false,
}: {
  offer: Recommendation;
  onSelect?: () => void;
  highlight?: boolean;
}) {
  const image = offer.items.find((item) => item.image_url)?.image_url;
  const closed = offer.is_open === false;
  const fees =
    (offer.delivery_fee_cents ?? 0) === 0
      ? "Entrega grátis"
      : `Entrega ${money(offer.delivery_fee_cents)}`;
  return (
    <View
      style={[
        s.card,
        { padding: 0, overflow: "hidden", gap: 0 },
        highlight && { borderColor: "#FFB3B7", borderWidth: 1.5 },
      ]}
    >
      <View style={{ flexDirection: "row", gap: 14, padding: 16, alignItems: "center" }}>
        {image ? (
          <Image
            source={{ uri: image }}
            accessibilityLabel={offer.items[0]?.name}
            style={{ width: 72, height: 72, borderRadius: 12, backgroundColor: "#F3F3F3" }}
          />
        ) : (
          <View style={[s.icon, { width: 72, height: 72, borderRadius: 12 }]}>
            <Icon name="food" size={30} />
          </View>
        )}
        <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
          {highlight && <Pill text="Recomendação principal" tone="red" />}
          <Text style={[s.heading, { fontSize: 18, lineHeight: 24 }]} numberOfLines={2}>
            {offer.merchant_name}
          </Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
            {offer.merchant_rating != null && (
              <View style={{ flexDirection: "row", gap: 4, alignItems: "center" }}>
                <Icon name="star" size={12} color={colors.amber} />
                <Text style={[s.muted, { fontSize: 13 }]}>{offer.merchant_rating.toFixed(1)}</Text>
              </View>
            )}
            <Text style={[s.muted, { fontSize: 13 }]}>{etaText(offer)}</Text>
            {offer.distance_km != null && (
              <Text style={[s.muted, { fontSize: 13 }]}>{offer.distance_km.toFixed(1)} km</Text>
            )}
            <Text style={[s.muted, { fontSize: 13 }]}>{fees}</Text>
          </View>
        </View>
      </View>

      <View style={{ paddingHorizontal: 16, gap: 6 }}>
        {offer.items.map((item) => (
          <View key={item.product_id} style={{ flexDirection: "row", gap: 8 }}>
            <Text style={[s.text, { flex: 1, fontSize: 16, lineHeight: 22 }]}>
              {item.quantity}× {item.name}
            </Text>
            <View style={{ alignItems: "flex-end" }}>
              {item.original_unit_price_cents != null && item.original_unit_price_cents > item.unit_price_cents && (
                <Text style={[s.muted, { fontSize: 12, lineHeight: 16, textDecorationLine: "line-through" }]}>
                  {money(item.original_unit_price_cents)}
                </Text>
              )}
              <Text style={[s.text, { fontSize: 16, lineHeight: 22 }]}>{money(item.unit_price_cents)}</Text>
            </View>
          </View>
        ))}
      </View>

      <View
        style={{
          margin: 16,
          marginTop: 12,
          padding: 12,
          borderRadius: 12,
          backgroundColor: colors.soft,
          flexDirection: "row",
          alignItems: "center",
        }}
      >
        <Text style={[s.muted, { flex: 1 }]}>Total{offer.other_fees_cents == null ? " (sem taxa de serviço)" : ""}</Text>
        <Text style={[s.metric, { fontSize: 22, lineHeight: 28 }]}>{money(offer.total_cents ?? offer.subtotal_cents)}</Text>
      </View>

      {(offer.reasons.length > 0 || offer.warnings.length > 0) && (
        <View style={{ paddingHorizontal: 16, paddingBottom: 14, gap: 6 }}>
          {offer.reasons.slice(0, 3).map((reason, index) => (
            <Text key={`reason-${index}`} style={[s.muted, { color: colors.green }]}>
              ✓ {reason}
            </Text>
          ))}
          {offer.warnings.slice(0, 3).map((warning, index) => (
            <Text key={`warning-${index}`} style={[s.muted, { color: colors.amber }]}>
              ⚠ {warning}
            </Text>
          ))}
        </View>
      )}

      {onSelect && (
        <View style={{ padding: 16, paddingTop: 0 }}>
          <Button
            title={closed ? "Restaurante fechado" : "Comprar"}
            onPress={onSelect}
            disabled={offer.total_cents === null || closed}
          />
        </View>
      )}
    </View>
  );
}
