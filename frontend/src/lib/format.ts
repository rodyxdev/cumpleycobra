// Presentación de montos, tiempos y enlaces. Los montos viajan siempre como enteros en
// unidades del token (1 USDC = 10_000_000); aquí solo se convierten para mostrarlos.

export const UNITS_PER_USDC = 10_000_000;

export function formatUsdc(units: number): string {
  const whole = Math.floor(units / UNITS_PER_USDC);
  const cents = Math.floor((units % UNITS_PER_USDC) / (UNITS_PER_USDC / 100));
  return `${whole.toLocaleString("es-MX")}.${String(cents).padStart(2, "0")} USDC`;
}

/** "1.5" -> 15000000. Sin float: se parte el texto en entero y decimales. */
export function parseUsdc(text: string): number | null {
  const m = text.trim().match(/^(\d+)(?:\.(\d{1,7}))?$/);
  if (!m) return null;
  const units = Number(m[1]) * UNITS_PER_USDC + Number((m[2] ?? "").padEnd(7, "0"));
  return Number.isSafeInteger(units) && units > 0 ? units : null;
}

export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function explorerTx(hash: string): string {
  return `https://stellar.expert/explorer/testnet/tx/${hash}`;
}

export function shortHash(hash: string, size = 8): string {
  return hash.length > size * 2 ? `${hash.slice(0, size)}…${hash.slice(-size)}` : hash;
}

export function isStellarAddress(addr: string): boolean {
  return /^G[A-Z2-7]{55}$/.test(addr.trim());
}

export const STATUS_LABEL: Record<string, string> = {
  Funded: "Depositada",
  Released: "Pagada",
  Refunded: "Reembolsada",
};
