"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, type Verdict } from "@/lib/api";
import { explorerTx } from "@/lib/format";

// Terminal honesta: cada línea sale de un hecho real (la petición enviada, el tiempo medido
// con el reloj del navegador o un campo de la respuesta del backend). Nada inventado.

type Line =
  | { kind: "cmd" | "muted" | "text" | "ok" | "err" | "warn"; text: string }
  | { kind: "wait"; startedAt: number }
  | { kind: "link"; text: string; href: string };

const LINE_DELAY_MS = 45; // solo ritmo de impresión; el contenido ya llegó completo

export function useTerminal() {
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(0);

  // Mientras hay una línea de espera, se vuelve a dibujar cada 100 ms para el contador.
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [busy]);

  const push = useCallback((l: Line) => setLines((prev) => [...prev, l]), []);

  const run = useCallback(
    async (label: string, send: () => Promise<Verdict>) => {
      setBusy(true);
      const startedAt = Date.now();
      setNow(startedAt);
      setLines([{ kind: "cmd", text: `$ POST /evaluate · ${label}` }, { kind: "wait", startedAt }]);
      let verdict: Verdict | null = null;
      let error: ApiError | null = null;
      try {
        verdict = await send();
      } catch (e) {
        error = e instanceof ApiError ? e : new ApiError(0, "ERROR", String(e));
      }
      const secs = ((Date.now() - startedAt) / 1000).toFixed(1);
      setBusy(false);

      if (error) {
        setLines((prev) => [
          ...prev.filter((l) => l.kind !== "wait"),
          { kind: "muted", text: `Respuesta en ${secs} s` },
          { kind: "err", text: `Error ${error.status || ""} ${error.code}: ${error.message}`.replace("  ", " ") },
        ]);
        return null;
      }
      const v = verdict!;
      setLines((prev) => [
        ...prev.filter((l) => l.kind !== "wait"),
        { kind: "muted", text: `Respuesta en ${secs} s · capa: ${stageLabel(v.stage)} · envíos usados: ${v.submissions_used}` },
      ]);
      const out: Line[] = [
        ...v.analysis.map((a): Line => ({ kind: lineKind(a), text: a })),
        ...v.security_flags.map((f): Line => ({ kind: "warn", text: `Alerta de seguridad: ${f}` })),
        { kind: v.approved ? "ok" : "err", text: v.approved ? "Veredicto: APROBADO" : "Veredicto: RECHAZADO" },
        { kind: "text", text: v.reason },
        { kind: "muted", text: `code_hash ${v.code_hash}` },
        { kind: "muted", text: `verdict_hash ${v.verdict_hash}` },
      ];
      if (v.transaction_hash) {
        out.push({ kind: "ok", text: "Pago liberado en el contrato." });
        out.push({ kind: "link", text: `Transacción ${v.transaction_hash}`, href: explorerTx(v.transaction_hash) });
      } else {
        out.push({ kind: "muted", text: "Sin pago: transaction_hash = null" });
      }
      for (const l of out) {
        await new Promise((r) => setTimeout(r, LINE_DELAY_MS));
        push(l);
      }
      return v;
    },
    [push],
  );

  return { lines, busy, now, run };
}

function stageLabel(stage: Verdict["stage"]): string {
  return { deterministic: "determinista", llm: "Gemini", cache: "caché" }[stage] ?? stage;
}

function lineKind(text: string): "ok" | "err" | "text" {
  const t = text.trimStart();
  if (t.startsWith("✓")) return "ok";
  if (t.startsWith("✗")) return "err";
  return "text";
}

export function Terminal({ lines, now }: { lines: Line[]; now: number }) {
  const bottom = useRef<HTMLDivElement>(null);
  // Con llaves: scrollIntoView puede devolver una promesa y React la tomaría como limpieza.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length]);

  return (
    <div
      className="h-80 overflow-y-auto rounded-xl bg-neutral-950 p-4 font-mono text-xs leading-relaxed text-neutral-200"
      data-testid="terminal"
    >
      {lines.length === 0 && <div className="text-neutral-500">La salida del motor de análisis aparece aquí.</div>}
      {lines.map((l, i) => {
        if (l.kind === "wait") {
          const secs = (Math.max(0, now - l.startedAt) / 1000).toFixed(1);
          return (
            <div key={i} className="text-amber-300">
              Enviando al motor de análisis… {secs} s
            </div>
          );
        }
        if (l.kind === "link") {
          return (
            <a key={i} href={l.href} target="_blank" rel="noreferrer" className="block text-sky-300 underline" data-testid="tx-link">
              {l.text}
            </a>
          );
        }
        const color = {
          cmd: "text-neutral-400",
          muted: "text-neutral-500",
          text: "text-neutral-200",
          ok: "text-emerald-400",
          err: "text-red-400",
          warn: "text-amber-300",
        }[l.kind];
        return (
          <div key={i} className={`whitespace-pre-wrap ${color}`}>
            {l.text}
          </div>
        );
      })}
      <div ref={bottom} />
    </div>
  );
}
