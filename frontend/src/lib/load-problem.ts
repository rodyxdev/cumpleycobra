// Qué decir cuando una página no puede cargar su dato principal (sin dejar al usuario sin salida).

export type LoadProblem = {
  title: string;
  text: string;
  /** true: el problema es pasajero (red, RPC, backend) y la página reintenta sola. */
  transient: boolean;
};

export function loadProblem(
  code: string | null | undefined,
  status = 0,
  message = "",
  what: "tarea" | "perfil" = "tarea",
): LoadProblem {
  if (code === "TASK_NOT_FOUND" || status === 404) {
    return {
      title: what === "perfil" ? "Este perfil no existe" : "Esta tarea no existe",
      text: "Revisa que el enlace esté completo. Si te lo compartieron, pide que te lo vuelvan a enviar.",
      transient: false,
    };
  }
  if (code === "INVALID_REQUEST" || status === 400) {
    return {
      title: "El enlace no es válido",
      text: what === "perfil"
        ? "La dirección del enlace no es una cuenta de Stellar válida (empieza con G y tiene 56 caracteres)."
        : message || "El identificador del enlace no tiene el formato esperado.",
      transient: false,
    };
  }
  if (code === "NOT_CONFIGURED") {
    return { title: "Falta configurar el servidor", text: message, transient: false };
  }
  if (code === "CHAIN_UNAVAILABLE") {
    return {
      title: "La red de Stellar no respondió",
      text: "El contrato es la fuente de verdad y no se pudo leer. Se vuelve a intentar en unos segundos.",
      transient: true,
    };
  }
  return {
    title: "No se pudo conectar con el servidor",
    text: "Puede ser tu conexión o el servidor. Se vuelve a intentar en unos segundos.",
    transient: true,
  };
}
