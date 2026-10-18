import React from "react";
import { Pressable, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { BrandGradient, Icon } from "./Brand";
import { styles as s, money } from "../theme";
import type { Recommendation } from "../types/api";

export function Button({
  title,
  onPress,
  disabled = false,
  icon,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  icon?: string;
}) {
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
      <BrandGradient
        style={[
          s.button,
          icon
            ? {
                width: 48,
                height: 48,
                paddingHorizontal: 0,
                paddingVertical: 0,
              }
            : {},
        ]}
      >
        {icon ? (
          <Icon name={icon} size={21} />
        ) : (
          <Text style={s.buttonText}>{title}</Text>
        )}
      </BrandGradient>
    </Pressable>
  );
}

export function Card({
  title,
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <View style={s.card}>
      {title && <Text style={s.heading}>{title}</Text>}
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

export function Badge({ text }: { text: string }) {
  const status = text.toLowerCase();

  const isOpen = ["em aberto", "open"].includes(status);
  const isResolved = ["concluído", "resolved"].includes(status);

  if (isOpen || isResolved) {
    return (
      <LinearGradient
        colors={
          isOpen
            ? ["#FFCD72", "#FF9D20"]
            : ["#40D35D", "#0BA732"]
        }
        style={{
          alignSelf: "flex-start",
          paddingHorizontal: 16,
          paddingVertical: 5,
          borderRadius: 16,
        }}
      >
        <Text
          style={[
            s.muted,
            {
              color: "#FFFFFF",
              fontFamily: "InterMedium",
            },
          ]}
        >
          {text}
        </Text>
      </LinearGradient>
    );
  }

  return <Text style={s.badge}>{text}</Text>;
}

export function Offer({
  offer,
  onSelect,
}: {
  offer: Recommendation;
  onSelect?: () => void;
}) {
  return (
    <Card>
      <View style={[s.row, { alignItems: "center" }]}>
        <View style={[s.icon, { width: 58, height: 58 }]}>
          <Icon name="file" size={28} />
        </View>

        <View style={{ flex: 1, minWidth: 140 }}>
          <Text style={s.heading}>{offer.merchant_name}</Text>
          <Text style={s.metric}>{money(offer.total_cents)}</Text>

          <Text style={s.muted}>
            {offer.eta_minutes == null
              ? "Prazo a confirmar"
              : `${offer.eta_minutes} min`}
            {" · "}
            {offer.data_origin === "demo"
              ? "Demonstração"
              : "iFood"}
            {offer.is_open === false ? " · Fechado — somente teste" : ""}
          </Text>
        </View>
      </View>

      {offer.items.map((item) => (
        <Text key={item.product_id} style={s.text}>
          {item.quantity} × {item.name}
          {" · "}
          {money(item.unit_price_cents)}
        </Text>
      ))}

      <Text style={s.muted}>
        Subtotal: {money(offer.subtotal_cents)}
        {"\n"}
        Entrega: {money(offer.delivery_fee_cents)}
        {"\n"}
        Taxas: {money(offer.other_fees_cents)}
        {"\n"}
        Desconto: {money(offer.discount_cents)}
      </Text>

      {offer.reasons.map((reason, index) => (
        <Text key={`reason-${index}`} style={s.text}>
          ✓ {reason}
        </Text>
      ))}

      {offer.warnings.map((warning, index) => (
        <Text key={`warning-${index}`} style={s.muted}>
          {warning}
        </Text>
      ))}

      {onSelect && (
        <Button
          title="Revisar pedido"
          onPress={onSelect}
          disabled={offer.total_cents === null || offer.is_open === false}
        />
      )}
    </Card>
  );
}
