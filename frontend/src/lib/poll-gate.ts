// Una consulta a la vez y solo cuenta la respuesta más reciente. Lógica pura, probada en tests/.
//
// El sondeo periódico no se lanza si hay una consulta en vuelo. Un refresco forzado (tras aceptar,
// enviar o firmar) sí se lanza, y la consulta anterior queda vieja: su respuesta se descarta, así
// una respuesta lenta de antes de aceptar no borra el estado nuevo.

export type PollGate = {
  /** Número de la consulta, o null si no toca lanzarla. */
  begin(force?: boolean): number | null;
  isCurrent(id: number): boolean;
  end(id: number): void;
};

export function createPollGate(): PollGate {
  let latest = 0;
  let inFlight = false;
  return {
    begin(force = false) {
      if (inFlight && !force) return null;
      inFlight = true;
      latest += 1;
      return latest;
    },
    isCurrent(id) {
      return id === latest;
    },
    end(id) {
      if (id === latest) inFlight = false;
    },
  };
}
