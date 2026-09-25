// Textos y reglas de la reputación del programador. Lógica pura, probada en tests/.

export const MAX_COMMENT = 280;

export const HONEST_NOTE =
  "Cada tarea de este historial se pagó en Stellar; las pagadas por el motor tienen el veredicto como hash on-chain.";

/** «4.5 de 5 · 2 calificaciones» o «Sin calificaciones». */
export function ratingLabel(average: number | null, count: number): string {
  if (!count || average === null) return "Sin calificaciones";
  const avg = average.toLocaleString("es-MX", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${avg} de 5 · ${count} ${count === 1 ? "calificación" : "calificaciones"}`;
}

export function paidByLabel(paidBy: "motor" | "manual"): string {
  return paidBy === "motor" ? "Pagada por el motor" : "Pagada por aprobación manual";
}

/** Mismas reglas que el backend: 1 a 5 estrellas enteras y comentario de hasta 280 caracteres. */
export function ratingProblem(estrellas: number, comentario: string): string | null {
  if (!Number.isInteger(estrellas) || estrellas < 1 || estrellas > 5) return "Elige de 1 a 5 estrellas.";
  if (comentario.length > MAX_COMMENT) return `El comentario admite hasta ${MAX_COMMENT} caracteres.`;
  return null;
}

/** Fecha ISO del ledger a «25 sep 2026», o «Fecha no disponible». */
export function paidDate(iso: string | null): string {
  if (!iso) return "Fecha no disponible";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Fecha no disponible";
  return d.toLocaleDateString("es-MX", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
