import { StyleSheet } from "react-native";

export const colors = {
  red: "#FF454E",
  ink: "#373737",
  muted: "#737373",
  line: "#E8E8E8",
  paper: "#FFFFFF",
  soft: "#FAFAFA",
  green: "#13A538",
  greenSoft: "#E9F8EC",
  amber: "#E58A00",
  amberSoft: "#FFF4E0",
  blue: "#2F6FDE",
  blueSoft: "#EAF1FD",
  redSoft: "#FFF0F1",
};

// Rótulos em português para estados que chegam crus da API.
export const agentStatusLabel: Record<string, string> = {
  idle: "Ocioso",
  running: "Trabalhando",
  waiting: "Aguardando",
  done: "Concluído",
  error: "Com erro",
};

export const sessionStatusLabel: Record<string, string> = {
  active: "Em andamento",
  waiting_customer: "Aguardando cliente",
  closed: "Encerrado",
  error: "Com erro",
};

export function relativeTime(iso: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "agora";
  if (seconds < 3600) return `há ${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `há ${Math.round(seconds / 3600)} h`;
  return new Date(iso).toLocaleDateString("pt-BR");
}

export const percent = (value: number | null | undefined) =>
  value == null || !isFinite(value) ? "—" : `${Math.round(value * 100)}%`;

// Controle os tamanhos gerais aqui.
export const fontSizes = {
  title: 30,
  heading: 22,
  body: 18,
  caption: 15,
  button: 16,
  metric: 30,
};

export const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: colors.paper,
  },

  content: {
    padding: 28,
    gap: 24,
    flexGrow: 1,
  },

  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 16,
  },

  card: {
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 14,
    padding: 18,
    gap: 12,
    shadowColor: "#000000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },

  title: {
    fontFamily: "InterSemiBold",
    fontSize: fontSizes.title,
    lineHeight: 38,
    color: colors.ink,
  },

  heading: {
    fontFamily: "InterSemiBold",
    fontSize: fontSizes.heading,
    lineHeight: 30,
    color: colors.ink,
  },

  text: {
    fontFamily: "Inter",
    fontSize: fontSizes.body,
    lineHeight: 27,
    color: colors.ink,
  },

  muted: {
    fontFamily: "Inter",
    fontSize: fontSizes.caption,
    lineHeight: 23,
    color: colors.muted,
  },

  button: {
    minHeight: 46,
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
  },

  buttonText: {
    fontFamily: "InterMedium",
    fontSize: fontSizes.button,
    lineHeight: 22,
    color: "#FFFFFF",
  },

  input: {
    minHeight: 50,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 25,
    paddingHorizontal: 18,
    paddingVertical: 12,
    fontFamily: "Inter",
    fontSize: fontSizes.body,
    color: colors.ink,
    backgroundColor: colors.paper,
  },

  metric: {
    fontFamily: "InterSemiBold",
    fontSize: fontSizes.metric,
    lineHeight: 38,
    color: colors.ink,
  },

  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 16,
    backgroundColor: "#FFF0F1",
    color: "#C6202C",
    fontFamily: "InterMedium",
    fontSize: fontSizes.caption,
    lineHeight: 21,
  },

  error: {
    padding: 14,
    borderRadius: 12,
    backgroundColor: "#FFF1F2",
    color: "#B51D2A",
    fontFamily: "Inter",
    fontSize: fontSizes.caption,
    lineHeight: 23,
  },

  side: {
    width: 224,
    padding: 16,
    paddingTop: 28,
    gap: 30,
    borderTopRightRadius: 20,
    borderBottomRightRadius: 20,
  },

  nav: {
    paddingVertical: 8,
    fontFamily: "Inter",
    fontSize: 16,
    lineHeight: 24,
    color: "#FFFFFF",
  },

  bubble: {
    maxWidth: "85%",
    padding: 16,
    borderRadius: 20,
    gap: 6,
  },

  divider: {
    height: 1,
    backgroundColor: colors.line,
  },

  icon: {
    width: 42,
    height: 42,
    borderRadius: 9,
    backgroundColor: "#FF545C",
    alignItems: "center",
    justifyContent: "center",
  },

  empty: {
    paddingVertical: 16,
    fontFamily: "Inter",
    fontSize: fontSizes.caption,
    lineHeight: 23,
    color: colors.muted,
  },
});

export const money = (value: number | null | undefined) =>
  value == null
    ? "Indisponível"
    : new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
      }).format(value / 100);