// Clientes FICTÍCIOS da apresentação. O histórico e o cadastro de cada um ficam na memória do
// backend (backend/memory/demo_seed.py), associados ao nome enviado no initial_context.
import type { InitialContext } from "../types/api";

export type Persona = { name: string | null; emoji: string; about: string };

export const PERSONAS: Persona[] = [
  { name: "Ana Souza", emoji: "🥢", about: "Vegetariana, adora comida japonesa" },
  { name: "Bruno Lima", emoji: "🍕", about: "Pizza com a família, de olho no preço" },
  { name: "Carla Mendes", emoji: "🥗", about: "Intolerante à lactose, curte comida leve" },
  { name: "Diego Rocha", emoji: "🍔", about: "Hambúrguer no capricho, cliente fiel" },
  { name: null, emoji: "👤", about: "Sem histórico nem cadastro" },
];

export function personaContext(name: string | null): InitialContext | null {
  return name ? { name, age: null, location: null, preferences: [], restrictions: [] } : null;
}
