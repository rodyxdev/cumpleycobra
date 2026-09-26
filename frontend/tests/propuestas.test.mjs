import assert from "node:assert/strict";
import { test } from "node:test";
import { canDecideProposal, PROPOSAL_LABEL, proposalDisplayState, taskAvailableForProposal } from "../src/lib/proposals.ts";

test("solo se ofrecen tareas de la wallet activa que nadie haya aceptado", () => {
  const own = { client_address: "cliente", freelancer_address: null };
  assert.equal(taskAvailableForProposal(own, "cliente"), true);
  assert.equal(taskAvailableForProposal(own, "otra-wallet"), false);
  assert.equal(taskAvailableForProposal({ ...own, freelancer_address: "programador" }, "cliente"), false);
});

test("una propuesta rechazada o aceptada no vuelve a ofrecer decisiones", () => {
  const tarea = { freelancer_address: null };
  assert.equal(canDecideProposal({ estado: "pendiente", programador: "yo", tarea }), true);
  assert.equal(canDecideProposal({ estado: "rechazada", programador: "yo", tarea }), false);
  assert.equal(canDecideProposal({ estado: "aceptada", programador: "yo", tarea }), false);
});

test("la aceptación por invitación de otro programador retira las decisiones del buzón", () => {
  assert.equal(canDecideProposal({ estado: "pendiente", programador: "yo", tarea: { freelancer_address: "otra-persona" } }), false);
});

test("si la tarea ya está amarrada al destinatario, puede aceptar (recupera el mismo token)", () => {
  assert.equal(canDecideProposal({ estado: "pendiente", programador: "yo", tarea: { freelancer_address: "yo" } }), true);
});

test("pendiente con la tarea tomada por otro se muestra cerrada; el estado guardado no cambia", () => {
  const p = { estado: "pendiente", programador: "yo" };
  assert.equal(proposalDisplayState(p, "otra-persona"), "cerrada");
  assert.equal(PROPOSAL_LABEL.cerrada, "Cerrada: la tomó otro programador");
  assert.equal(p.estado, "pendiente");
  assert.equal(proposalDisplayState(p, null), "pendiente");
  assert.equal(proposalDisplayState(p, "yo"), "pendiente");
  assert.equal(proposalDisplayState({ estado: "aceptada", programador: "yo" }, "yo"), "aceptada");
  assert.equal(proposalDisplayState({ estado: "rechazada", programador: "yo" }, "otra-persona"), "rechazada");
});
