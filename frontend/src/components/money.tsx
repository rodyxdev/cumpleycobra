"use client";

import { useEffect, useState } from "react";
import { api, type Fx } from "@/lib/api";
import { formatUsdc } from "@/lib/format";

let pending: Promise<Fx> | null = null;
export function useFx() {
  const [fx, setFx] = useState<Fx | null>(null);
  useEffect(() => {
    let alive = true;
    pending ??= api.fx().catch(() => ({ rate: "17.50", as_of: "2026-09-24", source: "Referencia fija de respaldo (sin conexión)", fallback: true }));
    pending.then((value) => { if (alive) setFx(value); });
    return () => { alive = false; };
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

export function Money({ units }: { units: number }) {
  const fx = useFx();
  return <span className="inline-flex flex-col align-middle">
    <span>{fx ? `≈ ${(units / 10_000_000 * Number(fx.rate)).toLocaleString("es-MX", { style: "currency", currency: "MXN" })} MXN` : "Calculando pesos…"}</span>
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
