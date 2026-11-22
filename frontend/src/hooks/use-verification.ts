"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { LINE_DELAY_MS, stageLabel, verdictLines, type Line } from "@/components/terminal";
import { api, ApiError, type Verdict, type VerificationSource } from "@/lib/api";
import { isFinal, progressLines } from "@/lib/verification";

const POLL_MS = 1500;

/**
 * Verificación por ejecución (fase 3): encola la entrega y consulta GET /verificaciones/{id}.
 * La terminal solo imprime hechos: la petición, cada evento de avance que informó el verificador
 * (con su segundo real) y, al final, los campos del veredicto.
 */
export function useVerification() {
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(0);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [busy]);

  const start = useCallback(async (taskId: string, address: string, token: string, label: string,
    source: VerificationSource, videoUrl: string | null): Promise<Verdict | null> => {
    setBusy(true);
    setVerdict(null);
    const startedAt = Date.now();
    setNow(startedAt);
    const head: Line[] = [{ kind: "cmd", text: `$ POST /tasks/${taskId}/verificaciones · ${label}` }];
    setLines([...head, { kind: "wait", startedAt, label: "En la cola del verificador (si estaba apagado, encenderlo tarda 1 o 2 minutos)…" }]);

    const fail = (e: unknown) => {
      const err = e instanceof ApiError ? e : new ApiError(0, "ERROR", String(e));
      setLines((prev) => [...prev.filter((l) => l.kind !== "wait"),
        { kind: "err", text: `Error ${err.status || ""} ${err.code}: ${err.message}`.replace("  ", " ") }]);
      setBusy(false);
      return null;
    };

    let id: string;
    try {
      id = (await api.verify(taskId, address, source, token, videoUrl)).verification_id;
    } catch (e) {
      return fail(e);
    }
    head.push({ kind: "muted", text: `verificación ${id}` });

    for (;;) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      if (!alive.current) return null;
      let status;
      try {
        status = await api.verification(id, { freelancer: token });
      } catch (e) {
        if (e instanceof ApiError && e.status === 0) continue; // falla de red: se vuelve a consultar
        return fail(e);
      }
      const events: Line[] = progressLines(status).map((p) => ({ kind: "text", text: `[${p.seconds.toFixed(1)} s] ${p.text}` }));
      if (!isFinal(status)) {
        const last = status.progress[status.progress.length - 1];
        setLines([...head, ...events, { kind: "wait", startedAt, label: last ? `${last.label}…` : "En la cola del verificador (si estaba apagado, encenderlo tarda 1 o 2 minutos)…" }]);
        continue;
      }
      const secs = ((Date.now() - startedAt) / 1000).toFixed(1);
      if (status.status === "failed" || !status.result) {
        setLines([...head, ...events, { kind: "muted", text: `Terminó en ${secs} s` },
          { kind: "err", text: status.message ?? "El verificador no pudo terminar; el envío no se contó." }]);
        setBusy(false);
        return null;
      }
      const v = status.result;
      setLines([...head, ...events,
        { kind: "muted", text: `Veredicto en ${secs} s · etapa: ${stageLabel(v.stage)} · envíos usados: ${status.submissions_used}` }]);
      setBusy(false);
      for (const l of verdictLines(v)) {
        await new Promise((r) => setTimeout(r, LINE_DELAY_MS));
        if (!alive.current) return v;
        setLines((prev) => [...prev, l]);
      }
      setVerdict(v);
      return v;
    }
  }, []);

  return { lines, busy, now, verdict, start };
}
