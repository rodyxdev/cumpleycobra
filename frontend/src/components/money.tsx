"use client";

import { useEffect, useState } from "react";
import { api, type Fx } from "@/lib/api";
import { formatUsdc } from "@/lib/format";
import { FX_RETRY_MS, shouldRefetch } from "@/lib/fx-cache";

const OFFLINE: Fx = { rate: "17.50", as_of: "2026-09-24", source: "Referencia fija de respaldo (sin conexión)", fallback: true };

// Una consulta compartida por todos los montos de la página. Una referencia real se conserva en la
// sesión; una de respaldo se vuelve a pedir a los 60 s (fx-cache.ts).
let cached: { promise: Promise<Fx>; at: number; value?: Fx } | null = null;
function loadFx(now: number): Promise<Fx> {
  if (!cached || shouldRefetch(cached.value, cached.at, now)) {
    const entry: NonNullable<typeof cached> = { promise: api.fx().catch(() => OFFLINE), at: now };
    entry.promise.then((value) => { entry.value = value; });
    cached = entry;
  }
  return cached.promise;
}

export function useFx() {
  const [fx, setFx] = useState<Fx | null>(null);
  useEffect(() => {
    let alive = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const tick = () => loadFx(Date.now()).then((value) => {
      if (!alive) return;
      setFx(value);
      if (value.fallback) retry = setTimeout(tick, FX_RETRY_MS);
    });
    tick();
    return () => { alive = false; clearTimeout(retry); };
  }, []);
  return fx;
}

/** Conversión decimal exacta a unidades USDC; redondeo hacia arriba a una unidad. */
export function parsePesos(text: string, rate: string): number | null {
  const amount = text.trim().match(/^(\d+)(?:\.(\d{1,2}))?$/);
  const quote = rate.match(/^(\d+)(?:\.(\d+))?$/);
  if (!amount || !quote) return null;
  const cents = BigInt(amount[1]) * BigInt(100) + BigInt((amount[2] ?? "").padEnd(2, "0"));
  const scale = BigInt(10) ** BigInt(quote[2]?.length ?? 0);
  const value = BigInt(quote[1]) * scale + BigInt(quote[2] || "0");
  if (cents <= BigInt(0) || value <= BigInt(0)) return null;
  const units = (cents * scale * BigInt(10_000_000) + value * BigInt(100) - BigInt(1)) / (value * BigInt(100));
  return units <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(units) : null;
}

/** Pesos primero y USDC debajo; con `inline`, en la misma línea para no romper una frase. */
export function Money({ units, inline = false }: { units: number; inline?: boolean }) {
  const fx = useFx();
  const pesos = fx ? `≈ ${(units / 10_000_000 * Number(fx.rate)).toLocaleString("es-MX", { style: "currency", currency: "MXN" })} MXN` : "Calculando pesos…";
  if (inline) return <span>{pesos} <span className="text-muted-foreground">({formatUsdc(units)})</span></span>;
  return <span className="inline-flex flex-col align-middle">
    <span>{pesos}</span>
    <span className="text-xs font-normal text-muted-foreground">{formatUsdc(units)}</span>
  </span>;
}

export function FxNotice() {
  const fx = useFx();
  return <p className="text-xs text-muted-foreground">
    {fx ? <>Estimado con tipo de cambio de referencia del {fx.as_of}; el monto final depende de la rampa de retiro.
      {" "}{fx.source}.{fx.fallback && " Se está usando un valor de respaldo."} El depósito se realiza en USDC.</> : "Consultando el tipo de cambio de referencia…"}
  </p>;
}
