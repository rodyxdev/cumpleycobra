// Recalcula el rules_hash en el navegador con la misma definición del backend (backend/hashing.py):
// SHA-256 del JSON canónico (claves ordenadas, sin espacios, UTF-8, textos en NFC). Así cualquiera
// comprueba que los criterios que ve son exactamente los que quedaron en el contrato.

export type AcuerdoTarea = {
  task_id: string;
  description: string;
  criteria: string[];
  language: string;
  allowed_deps: string[];
  examples: { input: string; output: string }[];
  verification?: string | null;
  interface?: unknown;
  web?: unknown;
};

export type HitoAcuerdo = { index: number; title: string; criteria: string[] };

function normalize(value: unknown): unknown {
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("Solo se hashean enteros seguros, nunca decimales");
    return value;
  }
  if (typeof value === "string") return value.normalize("NFC");
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (v === undefined) continue;
      out[k.normalize("NFC")] = normalize(v);
    }
    return out;
  }
  throw new Error(`Tipo no soportado: ${typeof value}`);
}

function ordenar(a: string, b: string): number {
  // Python ordena por punto de código; para claves ASCII coincide con el orden de UTF-16.
  const ca = Array.from(a), cb = Array.from(b);
  for (let i = 0; i < Math.min(ca.length, cb.length); i++) {
    const d = ca[i].codePointAt(0)! - cb[i].codePointAt(0)!;
    if (d !== 0) return d;
  }
  return ca.length - cb.length;
}

function stringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stringify).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj).sort(ordenar).map((k) => `${JSON.stringify(k)}:${stringify(obj[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** El mismo texto que `canonical_bytes` del backend, antes de codificarlo en UTF-8. */
export function canonicalJson(value: unknown): string {
  return stringify(normalize(value));
}

/** El objeto acordado que entra al hash: v1 (lectura), v2 (ejecución) o v3 (un hito). */
export function objetoAcordado(task: AcuerdoTarea, hito?: { indice: number; de: number; titulo: string; criteria: string[] }) {
  const agreed: Record<string, unknown> = {
    version: 1,
    description: task.description,
    criteria: hito ? hito.criteria : task.criteria,
    language: task.language,
    allowed_deps: [...task.allowed_deps].sort(ordenar),
    examples: task.examples,
  };
  if (task.verification === "execution") {
    agreed.version = 2;
    agreed.verification = "execution";
    agreed.interface = task.interface ?? null;
    if (task.web !== undefined && task.web !== null) agreed.web = task.web;
  }
  if (hito) {
    agreed.version = 3;
    agreed.hito = { proyecto: task.task_id, indice: hito.indice, de: hito.de, titulo: hito.titulo };
  }
  return agreed;
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function rulesHashLocal(task: AcuerdoTarea, hito?: { indice: number; de: number; titulo: string; criteria: string[] }) {
  return sha256Hex(canonicalJson(objetoAcordado(task, hito)));
}
