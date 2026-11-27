// Archivo .ics del plazo on-chain (src/lib/calendario.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { icsPlazo } from "../src/lib/calendario.ts";

const base = { taskId: "Fzw_5tOvZG-FmM7o", deadline: 1795700000, url: "https://cumpleycobra.vercel.app/tarea/Fzw_5tOvZG-FmM7o", ahora: 1795690000 };

test("evento que termina en el plazo on-chain, en UTC y con CRLF", () => {
  const ics = icsPlazo(base);
  assert.ok(ics.startsWith("BEGIN:VCALENDAR\r\n") && ics.endsWith("END:VCALENDAR\r\n"));
  assert.match(ics, /\r\nDTEND:20261126T133320Z\r\n/);
  assert.match(ics, /\r\nDTSTART:20261126T130320Z\r\n/);
  assert.match(ics, /\r\nTRIGGER:-PT30M\r\n/);
  assert.ok(!/[^\r]\n/.test(ics), "solo saltos CRLF");
});

test("escapa comas y punto y coma, y dobla líneas largas a 75 octetos", () => {
  const ics = icsPlazo({ ...base, taskId: "a,b;c" });
  assert.match(ics, /UID:a\\,b\\;c@cumpleycobra/);
  for (const linea of ics.split("\r\n")) assert.ok(new TextEncoder().encode(linea).length <= 75, linea);
  // Al desdoblar se recupera el texto original.
  assert.match(ics.replace(/\r\n /g, ""), /DESCRIPTION:Plazo on-chain del contrato\. Después/);
});
