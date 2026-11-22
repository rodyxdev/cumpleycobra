// Verificación por ejecución (fase 3): lógica pura, probada en tests/verificacion.test.mjs.

import type { Interface, Spec, SuitePlan, VerificationSource, VerificationStatus } from "./api.ts";

export const STAGE_LABEL: Record<string, string> = {
  deterministic: "determinista",
  llm: "Gemini",
  cache: "caché",
  hygiene: "higiene",
  build: "dependencias",
  static: "seguridad",
  tests: "tests ocultos",
  judge: "juez",
  final: "regla final",
};

export const TIPO_LABEL: Record<string, string> = {
  test: "Se comprueba ejecutando",
  lectura: "Se comprueba leyendo el código",
  navegador: "Se comprueba en un navegador",
  visual: "Lo juzga el modelo con capturas",
};

const PAGE = /^\/[A-Za-z0-9._~/-]{0,100}$/;

/** Páginas de un sitio web, separadas por comas o líneas: «/, /contacto». */
export function parsePages(raw: string): string[] | string {
  const pages = raw.split(/[\n,]+/).map((p) => p.trim()).filter(Boolean);
  if (pages.length === 0) return "Indica al menos una página, por ejemplo /.";
  if (pages.length > 5) return "Máximo 5 páginas.";
  const bad = pages.find((p) => !PAGE.test(p) || p.includes(".."));
  if (bad) return `«${bad}» no es una ruta válida: empieza con / y usa letras, números, - o _.`;
  if (new Set(pages).size !== pages.length) return "Hay páginas repetidas.";
  return pages;
}

export const SUITE_STATUS_LABEL: Record<SuitePlan["status"], string> = {
  pendiente: "Preparando la suite oculta",
  validando: "Validando la suite oculta",
  lista: "Suite oculta lista",
  rechazada: "No se pudo preparar la suite oculta",
};

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const MODULE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;

/**
 * Propone la interfaz a partir de la descripción: la primera firma `nombre(args) -> tipo`.
 * El cliente la revisa y la edita; solo es un punto de partida.
 */
export function guessInterface(spec: Pick<Spec, "description" | "criteria">): { module: string; name: string; signature: string } {
  const text = [spec.description, ...spec.criteria].join("\n");
  const match = text.match(/([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)\s*(->\s*[^,.;\n]+)?/);
  if (!match) return { module: "solucion", name: "", signature: "" };
  const name = match[1];
  const signature = `${name}(${match[2].trim()})${match[3] ? " " + match[3].trim() : ""}`;
  // aplicar_descuento → descuentos; resumir_ventas → ventas; sin guion bajo → solucion.
  const last = name.includes("_") ? name.split("_").filter(Boolean).slice(-1)[0] ?? "" : "";
  const moduleName = last && IDENT.test(last) ? (last.endsWith("s") ? last : `${last}s`) : "solucion";
  return { module: moduleName, name, signature };
}

export function interfaceProblem(module: string, name: string, signature: string): string | null {
  if (!MODULE.test(module.trim())) return "El módulo debe ser un nombre de Python (letras, números y _; puntos para paquetes).";
  if (!IDENT.test(name.trim())) return "La función debe ser un nombre de Python (letras, números y _).";
  if (!signature.trim().startsWith(`${name.trim()}(`)) return "La firma debe empezar con el nombre de la función, por ejemplo f(x: int) -> int.";
  if (signature.length > 300) return "La firma no puede pasar de 300 caracteres.";
  return null;
}

export function buildInterface(module: string, name: string, signature: string): Interface {
  return { language: "python", symbols: [{ module: module.trim(), name: name.trim(), kind: "function", signature: signature.trim() }] };
}

const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/;
const SHA = /^[0-9a-f]{40}$/;

/** Acepta «owner/repo», «https://github.com/owner/repo» o «…/tree/<sha>». */
export function parseRepo(raw: string, rawSha: string): { repo: string; sha: string } | string {
  let repo = raw.trim().replace(/^https?:\/\/github\.com\//, "").replace(/\.git$/, "").replace(/\/+$/, "");
  let sha = rawSha.trim().toLowerCase();
  const tree = repo.match(/^([^/]+\/[^/]+)\/(?:tree|commit)\/([0-9a-fA-F]{40})$/);
  if (tree) {
    repo = tree[1];
    sha = sha || tree[2].toLowerCase();
  }
  if (!REPO.test(repo)) return "El repositorio debe ser público y tener la forma owner/nombre.";
  if (!SHA.test(sha)) return "Indica el SHA completo del commit (40 caracteres hexadecimales): fija exactamente qué se verifica.";
  return { repo, sha };
}

export async function zipSource(file: { arrayBuffer(): Promise<ArrayBuffer>; size: number }, maxBytes = 2 * 1024 * 1024): Promise<VerificationSource | string> {
  if (file.size > maxBytes) return `El ZIP pesa más de ${Math.round(maxBytes / 1024 / 1024)} MB.`;
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return { kind: "zip", zip_b64: btoa(binary) };
}

export type ProgressLine = { key: string; text: string; seconds: number };

/** Una línea por evento real de avance, con el segundo en que ocurrió desde que se encoló. */
export function progressLines(status: Pick<VerificationStatus, "created_at" | "progress">): ProgressLine[] {
  return status.progress.map((p, i) => ({
    key: `${i}-${p.stage}`,
    text: p.detail ? `${p.label}: ${p.detail}` : p.label,
    seconds: Math.max(0, p.at - status.created_at),
  }));
}

export function isFinal(status: Pick<VerificationStatus, "status">): boolean {
  return status.status === "done" || status.status === "failed";
}
