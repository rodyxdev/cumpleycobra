// A dónde apunta el frontend. Lógica pura, probada en tests/.
//
// En producción (Vercel) NEXT_PUBLIC_API_URL es obligatoria: sin ella no se cae a localhost en
// silencio (el navegador del juez llamaría a su propia máquina); las peticiones fallan con un
// mensaje claro. En desarrollo, el respaldo es el backend local.

export const LOCAL_API = "http://localhost:8000";

export function resolveApiUrl(configured: string | undefined, nodeEnv: string | undefined): string {
  const value = (configured ?? "").trim().replace(/\/+$/, "");
  if (value) return value;
  return nodeEnv === "production" ? "" : LOCAL_API;
}
