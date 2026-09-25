// Identidad verificada (SEP-10) y perfil: reglas puras, probadas en tests/. Mismos límites que el backend.

export type Session = { token: string; address: string; expires_at: number };

export const MAX_NAME = 60;
export const MAX_SKILLS = 8;
export const MAX_SKILL = 30;
export const MAX_BIO = 280;

/** La sesión sirve si es de esa dirección y no ha caducado (expires_at en segundos). */
export function sessionIsValid(s: Session | null | undefined, address: string | null | undefined, nowMs: number): boolean {
  return !!s && !!address && s.address === address && s.expires_at * 1000 > nowMs;
}

/** «Python, FastAPI, python» → ["Python", "FastAPI"]: sin vacíos ni repetidos (sin distinguir mayúsculas). */
export function parseSkills(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const s = raw.trim();
    if (s && !out.some((x) => x.toLowerCase() === s.toLowerCase())) out.push(s);
  }
  return out;
}

export function profileProblem(nombre: string, skills: string[], bio: string): string | null {
  if (nombre.trim().length > MAX_NAME) return `El nombre admite hasta ${MAX_NAME} caracteres.`;
  if (skills.length > MAX_SKILLS) return `Hasta ${MAX_SKILLS} habilidades.`;
  if (skills.some((s) => s.length > MAX_SKILL)) return `Cada habilidad admite hasta ${MAX_SKILL} caracteres.`;
  if (bio.trim().length > MAX_BIO) return `La bio admite hasta ${MAX_BIO} caracteres.`;
  return null;
}
