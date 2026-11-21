// Modo de la app, igual que APP_MODE del backend (sin dependencias: se puede leer en el servidor).
//   local  tu laptop: muestra las ayudas para desarrollo (scripts de la terminal).
//   demo   enlace público en testnet: sin comandos de terminal, con el faucet de Circle y aviso de testnet.
//   live   usuarios reales.
// Sin NEXT_PUBLIC_APP_MODE, un build de producción es `demo` y `next dev` es `local`.

export type AppMode = "local" | "demo" | "live";

export function resolveAppMode(raw: string | undefined, nodeEnv: string | undefined): AppMode {
  const value = (raw ?? "").trim().toLowerCase();
  if (value === "local" || value === "demo" || value === "live") return value;
  return nodeEnv === "production" ? "demo" : "local";
}

export const APP_MODE: AppMode = resolveAppMode(process.env.NEXT_PUBLIC_APP_MODE, process.env.NODE_ENV);
export const SHOW_DEV_HINTS = APP_MODE === "local";

/** Faucet de USDC de testnet (Circle): se elige la red Stellar y se pega la dirección. */
export const USDC_FAUCET_URL = "https://faucet.circle.com/";
