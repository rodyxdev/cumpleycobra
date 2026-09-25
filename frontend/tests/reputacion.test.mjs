// Reputación del programador: textos y reglas del formulario, con el runner de Node.

import assert from "node:assert/strict";
import { test } from "node:test";

import { HONEST_NOTE, MAX_COMMENT, paidByLabel, paidDate, ratingLabel, ratingProblem } from "../src/lib/reputation.ts";

test("etiqueta de calificación", () => {
  assert.equal(ratingLabel(null, 0), "Sin calificaciones");
  assert.equal(ratingLabel(4.5, 2), "4.5 de 5 · 2 calificaciones");
  assert.equal(ratingLabel(5, 1), "5.0 de 5 · 1 calificación");
});

test("reglas del formulario iguales a las del backend", () => {
  assert.equal(ratingProblem(0, ""), "Elige de 1 a 5 estrellas.");
  assert.equal(ratingProblem(6, ""), "Elige de 1 a 5 estrellas.");
  assert.equal(ratingProblem(4.5, ""), "Elige de 1 a 5 estrellas.");
  assert.equal(ratingProblem(1, ""), null);
  assert.equal(ratingProblem(5, "x".repeat(MAX_COMMENT)), null);
  assert.match(ratingProblem(5, "x".repeat(MAX_COMMENT + 1)), /280/);
});

test("cómo se pagó, fecha y nota honesta", () => {
  assert.equal(paidByLabel("motor"), "Pagada por el motor");
  assert.equal(paidByLabel("manual"), "Pagada por aprobación manual");
  assert.equal(paidDate(null), "Fecha no disponible");
  assert.equal(paidDate("no-es-fecha"), "Fecha no disponible");
  assert.match(paidDate("2026-09-25T15:04:26Z"), /25.*2026/);
  assert.equal(HONEST_NOTE,
    "Cada tarea de este historial se pagó en Stellar; las pagadas por el motor tienen el veredicto como hash on-chain.");
});
