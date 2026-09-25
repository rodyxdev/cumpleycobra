// Cuándo volver a pedir el tipo de cambio. Lógica pura, probada en tests/.

export const FX_RETRY_MS = 60_000;

/** Una referencia de respaldo se vuelve a pedir a los 60 s; una real se conserva en la sesión. */
export function shouldRefetch(value: { fallback: boolean } | undefined, fetchedAt: number, now: number): boolean {
  return !!value?.fallback && now - fetchedAt >= FX_RETRY_MS;
}
