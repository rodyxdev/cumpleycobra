// Correcciones del frontend (auditoría): lógica pura de src/lib, con el runner de Node.
// Uso (desde frontend/): npm test   (Node 24 ejecuta los .ts quitando los tipos)

import assert from "node:assert/strict";
import { test } from "node:test";

import { manualApproval } from "../src/lib/approval.ts";
import { FX_RETRY_MS, shouldRefetch } from "../src/lib/fx-cache.ts";
import { createPollGate } from "../src/lib/poll-gate.ts";
import { BUSY_MESSAGE, sendRejection } from "../src/lib/send-status.ts";
import { verdictCardProps } from "../src/lib/verdict-view.ts";

const G = "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ";

// 14. La tarjeta usa los campos reales del veredicto, no líneas de la terminal.
test("tarjeta de veredicto con los datos de /evaluate", () => {
  const v = {
    approved: false,
    reason: "Rechazado por seguridad.",
    // La traza del modelo también empieza con ✓: el adaptador anterior las confundía con criterios.
    analysis: ["✓ traza que parece criterio", "✓ Criterio 1: sí", "✗ Criterio 2: no"],
    comparison: ["✓ Criterio 1: sí", "✗ Criterio 2: no"],
    security_flags: ["Instrucciones para el evaluador en el docstring"],
    transaction_hash: null,
  };
  assert.deepEqual(verdictCardProps(v), {
    approved: false, reason: v.reason, comparison: v.comparison,
    securityFlags: v.security_flags, transactionHash: null,
  });
});

// 15. Aprobado sin transaction_hash: el cliente puede pagar a mano.
test("aprobación manual con un veredicto aprobado sin pago", () => {
  const base = { status: "Funded", freelancer: G, secondsLeft: 300 };
  assert.deepEqual(manualApproval({ ...base, verdicts: [{ approved: true, transaction_hash: null }] }),
    { can: true, why: "approved-unpaid" });
  assert.deepEqual(manualApproval({ ...base, verdicts: [{ approved: true, transaction_hash: "aa" }] }),
    { can: false, why: null });
  assert.equal(manualApproval({ ...base, verdicts: [{ approved: false, transaction_hash: null }] }).why, "rejected");
  assert.equal(manualApproval({ ...base, secondsLeft: 0, verdicts: [] }).why, "expired");
  assert.equal(manualApproval({ ...base, status: "Released", verdicts: [{ approved: true, transaction_hash: null }] }).can, false);
  assert.equal(manualApproval({ ...base, freelancer: null, verdicts: [{ approved: false, transaction_hash: null }] }).can, false);
});

// 16. Un sondeo a la vez y se descarta la respuesta vieja.
test("sondeo: no se lanza otro en vuelo y la respuesta vieja se descarta", () => {
  const gate = createPollGate();
  const poll = gate.begin();          // sondeo periódico lento, antes de aceptar
  assert.equal(gate.begin(), null);   // el siguiente sondeo no se lanza
  const fresh = gate.begin(true);     // refresco forzado tras aceptar
  assert.notEqual(fresh, null);
  // Llega primero la respuesta nueva y después la vieja: solo la nueva cuenta.
  assert.equal(gate.isCurrent(fresh), true);
  gate.end(fresh);
  assert.equal(gate.isCurrent(poll), false);
  gate.end(poll);
  assert.notEqual(gate.begin(), null); // ya no hay nada en vuelo
});

// 18. TRY_AGAIN_LATER es un error con mensaje claro, no un envío exitoso.
test("sendTransaction TRY_AGAIN_LATER", () => {
  assert.equal(sendRejection("TRY_AGAIN_LATER"), BUSY_MESSAGE);
  assert.equal(BUSY_MESSAGE, "La red está ocupada; vuelve a intentar.");
  assert.equal(sendRejection("ERROR", "txBadSeq"), "La red rechazó la transacción al enviarla (txBadSeq).");
  assert.equal(sendRejection("PENDING"), null);
  assert.equal(sendRejection("DUPLICATE"), null);
});

// 19. Un respaldo del tipo de cambio se vuelve a pedir a los 60 s.
test("tipo de cambio de respaldo: reintento a los 60 s", () => {
  const t0 = 1_000_000;
  assert.equal(FX_RETRY_MS, 60_000);
  assert.equal(shouldRefetch({ fallback: true }, t0, t0 + 59_999), false);
  assert.equal(shouldRefetch({ fallback: true }, t0, t0 + 60_000), true);
  assert.equal(shouldRefetch({ fallback: false }, t0, t0 + 3_600_000), false);
  assert.equal(shouldRefetch(undefined, t0, t0 + 60_000), false); // la primera consulta sigue en vuelo
});
