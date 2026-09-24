"use client";

import { PollarProvider } from "@pollar/react";
import "@pollar/react/styles.css";

import { POLLAR_API_KEY } from "@/lib/config";

// La config se crea una vez: PollarProvider la fija en el primer render.
const pollarConfig = { apiKey: POLLAR_API_KEY, stellarNetwork: "testnet" as const };

export function Providers({ children }: { children: React.ReactNode }) {
  if (!POLLAR_API_KEY) return <>{children}</>; // sin API key: solo el respaldo con Freighter
  return <PollarProvider client={pollarConfig}>{children}</PollarProvider>;
}
