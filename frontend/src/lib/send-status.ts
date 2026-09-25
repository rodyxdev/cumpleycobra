// Respuesta de sendTransaction del RPC que impide seguir. Lógica pura, probada en tests/.

export const BUSY_MESSAGE = "La red está ocupada; vuelve a intentar.";

/** Mensaje de error para el estado de sendTransaction, o null si la transacción quedó enviada. */
export function sendRejection(status: string, errorCode?: string): string | null {
  // TRY_AGAIN_LATER: el nodo no aceptó la transacción por carga; no se envió, se puede reintentar.
  if (status === "TRY_AGAIN_LATER") return BUSY_MESSAGE;
  if (status === "ERROR") return `La red rechazó la transacción al enviarla (${errorCode ?? "desconocido"}).`;
  return null;
}
