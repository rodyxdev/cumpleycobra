import assert from "node:assert/strict";
import { test } from "node:test";
import { canDecideProposal, taskAvailableForProposal } from "../src/lib/proposals.ts";

test("solo se ofrecen tareas de la wallet activa que nadie haya aceptado", () => {
  const own = { client_address: "cliente", freelancer_address: null };
  assert.equal(taskAvailableForProposal(own, "cliente"), true);
  assert.equal(taskAvailableForProposal(own, "otra-wallet"), false);
  assert.equal(taskAvailableForProposal({ ...own, freelancer_address: "programador" }, "cliente"), false);
});

test("una propuesta rechazada o aceptada no vuelve a ofrecer decisiones", () => {
  const tarea = { freelancer_address: null };
  assert.equal(canDecideProposal({ estado: "pendiente", tarea }), true);
  assert.equal(canDecideProposal({ estado: "rechazada", tarea }), false);
  assert.equal(canDecideProposal({ estado: "aceptada", tarea }), false);
});

test("la aceptación por invitación también retira las decisiones del buzón", () => {
  assert.equal(canDecideProposal({ estado: "pendiente", tarea: { freelancer_address: "otra-persona" } }), false);
});
