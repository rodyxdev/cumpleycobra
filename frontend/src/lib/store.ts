"use client";

// Tokens de cada tarea en el localStorage de este navegador.
// Toda lectura y escritura va en try/catch: el almacenamiento puede no existir.

import { useMemo, useSyncExternalStore } from "react";

import { STORAGE_PREFIX, taskStorageKeys } from "@/lib/task-keys";

export type ClientTask = {
  task_id: string;
  client_token: string;
  invite_token: string;
  rules_hash: string;
  amount: number;
  deadline_minutes: number;
  client_address: string;
  created_at: number;
};

export type FreelancerTask = {
  task_id: string;
  freelancer_token: string;
  freelancer_address: string;
};

const PREFIX = STORAGE_PREFIX;
const EVENT = "cumpleycobra:storage";

function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(`${PREFIX}:${key}`);
  } catch {
    return null;
  }
}

function read<T>(key: string): T | null {
  const raw = readRaw(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(`${PREFIX}:${key}`, JSON.stringify(value));
  } catch {
    // Sin almacenamiento: la sesión sigue funcionando mientras la página esté abierta.
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  window.addEventListener(EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(EVENT, callback);
  };
}

/** Valor guardado, reactivo. En el servidor (y antes de hidratar) es null. */
export function useStored<T>(key: string | null): T | null {
  const raw = useSyncExternalStore(
    subscribe,
    () => (key ? readRaw(key) : null),
    () => null,
  );
  return useMemo(() => {
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  }, [raw]);
}

export const keys = {
  clientTask: (id: string) => `cliente:${id}`,
  clientTaskIds: "cliente:tareas",
  freelancerTask: (id: string) => `programador:${id}`,
  lastAddress: (role: "cliente" | "programador") => `direccion:${role}`,
  /** Sesión SEP-10 por dirección. «Limpiar lista» no la borra (no es una llave de tarea). */
  session: (address: string) => `sesion:${address}`,
};

export const store = {
  saveClientTask: (t: Omit<ClientTask, "created_at">) => {
    write(keys.clientTask(t.task_id), { ...t, created_at: Date.now() });
    const ids = read<string[]>(keys.clientTaskIds) ?? [];
    write(keys.clientTaskIds, [t.task_id, ...ids.filter((x) => x !== t.task_id)]);
  },
  saveFreelancerTask: (t: FreelancerTask) => write(keys.freelancerTask(t.task_id), t),
  saveLastAddress: (role: "cliente" | "programador", addr: string) => write(keys.lastAddress(role), addr),
  clientTask: (id: string) => read<ClientTask>(keys.clientTask(id)),
  saveSession: (s: { token: string; address: string; expires_at: number }) => write(keys.session(s.address), s),
  clearSession: (address: string) => {
    try {
      window.localStorage.removeItem(`${PREFIX}:${keys.session(address)}`);
    } catch {
      // Sin almacenamiento: no hay nada que borrar.
    }
    window.dispatchEvent(new Event(EVENT));
  },
  /** Borra solo las llaves de tareas (task-keys.ts); la sesión de Pollar queda intacta. */
  clearTasks: (): number => {
    let removed = 0;
    try {
      const all = Array.from({ length: window.localStorage.length }, (_, i) => window.localStorage.key(i) ?? "");
      for (const key of taskStorageKeys(all)) {
        window.localStorage.removeItem(key);
        removed += 1;
      }
    } catch {
      // Sin almacenamiento: no hay nada que borrar.
    }
    window.dispatchEvent(new Event(EVENT));
    return removed;
  },
};
