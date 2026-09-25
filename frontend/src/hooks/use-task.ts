"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, type TaskView } from "@/lib/api";
import { createPollGate } from "@/lib/poll-gate";

const POLL_MS = 3000;

/**
 * Consulta GET /tasks/{id} cada 3 s. El plazo restante sale del contrato (seconds_left,
 * calculado por el backend con el reloj del ledger) y entre consultas se descuenta localmente.
 */
export function useTask(taskId: string | null) {
  const [task, setTask] = useState<TaskView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const fetchedAt = useRef<{ at: number; left: number | null }>({ at: 0, left: null });
  // Una consulta a la vez; si un refresco forzado adelanta a un sondeo lento, la respuesta vieja
  // se descarta (contador de consultas dentro del gate).
  const [gate] = useState(createPollGate);

  const load = useCallback(async (force: boolean) => {
    if (!taskId) return;
    const id = gate.begin(force);
    if (id === null) return; // hay una consulta en vuelo
    try {
      const t = await api.task(taskId);
      if (!gate.isCurrent(id)) return;
      setTask(t);
      setError(null);
      fetchedAt.current = { at: Date.now(), left: t.seconds_left };
      setSecondsLeft(t.seconds_left);
    } catch (e) {
      if (gate.isCurrent(id)) setError(e instanceof ApiError ? e : new ApiError(0, "ERROR", String(e)));
    } finally {
      gate.end(id);
    }
  }, [taskId, gate]);

  // Tras aceptar, enviar o firmar: siempre consulta, aunque haya un sondeo en vuelo.
  const refresh = useCallback(() => load(true), [load]);

  useEffect(() => {
    if (!taskId) return;
    // Primera consulta inmediata y luego cada POLL_MS (setState ocurre dentro del callback async).
    const first = setTimeout(() => load(true), 0);
    const poll = setInterval(() => load(false), POLL_MS);
    const tick = setInterval(() => {
      const { at, left } = fetchedAt.current;
      if (left !== null) setSecondsLeft(left - Math.floor((Date.now() - at) / 1000));
    }, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [taskId, load]);

  return { task, error, secondsLeft, refresh };
}
