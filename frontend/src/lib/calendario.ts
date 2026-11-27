// Archivo .ics (RFC 5545) con el plazo on-chain de una tarea: el programador lo agrega a su calendario
// y recibe un aviso 30 minutos antes, cuando todavía alcanza para enviar (el motor exige 120 s).

function fechaUtc(segundos: number): string {
  return new Date(segundos * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function escapar(texto: string): string {
  return texto.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

/** Líneas de más de 75 octetos se doblan con CRLF + espacio, como pide el estándar. */
function doblar(linea: string): string {
  const bytes = new TextEncoder();
  const partes: string[] = [];
  let actual = "";
  for (const ch of linea) {
    if (bytes.encode(actual + ch).length > (partes.length ? 74 : 75)) {
      partes.push(actual);
      actual = ch;
    } else {
      actual += ch;
    }
  }
  partes.push(actual);
  return partes.join("\r\n ");
}

export function icsPlazo({ taskId, deadline, url, ahora }: { taskId: string; deadline: number; url: string; ahora: number }): string {
  const lineas = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Cumple&Cobra//Plazo de tarea//ES",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${escapar(taskId)}@cumpleycobra`,
    `DTSTAMP:${fechaUtc(ahora)}`,
    `DTSTART:${fechaUtc(deadline - 30 * 60)}`,
    `DTEND:${fechaUtc(deadline)}`,
    `SUMMARY:${escapar(`Vence el plazo de la tarea ${taskId} (Cumple&Cobra)`)}`,
    `DESCRIPTION:${escapar(`Plazo on-chain del contrato. Después de esta hora el motor ya no puede pagar y el depósito puede volver al cliente.\n${url}`)}`,
    `URL:${url}`,
    "BEGIN:VALARM",
    "ACTION:DISPLAY",
    "TRIGGER:-PT30M",
    `DESCRIPTION:${escapar("Quedan 30 minutos para entregar")}`,
    "END:VALARM",
    "END:VEVENT",
    "END:VCALENDAR",
  ];
  return lineas.map(doblar).join("\r\n") + "\r\n";
}
