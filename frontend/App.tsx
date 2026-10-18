import React, { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { useFonts } from "expo-font";
import { Inter_400Regular } from "@expo-google-fonts/inter/400Regular";
import { Inter_500Medium } from "@expo-google-fonts/inter/500Medium";
import { Inter_600SemiBold } from "@expo-google-fonts/inter/600SemiBold";
import { Inter_700Bold } from "@expo-google-fonts/inter/700Bold";
import { ChatScreen } from "./src/screens/ChatScreen";
import { OfficeScreen, OfficeTab } from "./src/screens/OfficeScreen";
import { BrandGradient, Wordmark } from "./src/components/Brand";
import { styles as s } from "./src/theme";
export default function App() {
  const [tab, setTab] = useState<OfficeTab | "Chatbot">("Chatbot");
  const wide = useWindowDimensions().width >= 850;
  const [loaded, fontError] = useFonts({
    Inter: Inter_400Regular,
    InterMedium: Inter_500Medium,
    InterSemiBold: Inter_600SemiBold,
    InterBold: Inter_700Bold,
  });
  if (!loaded && !fontError)
    return (
      <View
        style={[s.page, { alignItems: "center", justifyContent: "center" }]}
      >
        <ActivityIndicator color="#ff454e" />
      </View>
    );
  return (
    <SafeAreaView style={[s.page, { flexDirection: wide ? "row" : "column" }]}>
      {tab !== "Chatbot" && (
        <BrandGradient
          style={[
            s.side,
            !wide && {
              width: "100%",
              padding: 14,
              gap: 8,
              borderBottomRightRadius: 20,
            },
          ]}
        >
          <Wordmark />
          <View
            style={{
              flexDirection: wide ? "column" : "row",
              flexWrap: "wrap",
              gap: wide ? 10 : 15,
            }}
          >
            {(["Dashboard", "Painel de Agentes", "Conflitos"] as const).map(
              (t) => (
                <Pressable
                  key={t}
                  accessibilityRole="button"
                  accessibilityState={{ selected: tab === t }}
                  onPress={() => setTab(t)}
                  style={({ pressed }) => ({
                    opacity: pressed ? 0.65 : 1,
                    paddingVertical: 8,
                  })}
                >
                  <Text
                    style={[
                      s.nav,
                      { fontFamily: tab === t ? "InterBold" : "Inter" },
                    ]}
                  >
                    {t}
                  </Text>
                </Pressable>
              ),
            )}
          </View>
          <View style={wide ? { flex: 1 } : undefined} />
          <Pressable
            accessibilityRole="button"
            onPress={() => setTab("Chatbot")}
          >
            <Text style={s.nav}>Abrir chatbot ↗</Text>
          </Pressable>
        </BrandGradient>
      )}
      <View style={{ flex: 1 }}>
        <View style={{ flex: 1, display: tab === "Chatbot" ? "flex" : "none" }}>
          <ChatScreen onBack={() => setTab("Dashboard")} />
        </View>
        {tab !== "Chatbot" && <OfficeScreen tab={tab} />}
      </View>
    </SafeAreaView>
  );
}
