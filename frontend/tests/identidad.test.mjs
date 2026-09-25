// Identidad verificada y perfil: reglas puras del frontend (mismos límites que el backend).

import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_BIO, MAX_NAME, MAX_SKILL, parseSkills, profileProblem, sessionIsValid } from "../src/lib/identity.ts";
import { taskStorageKeys } from "../src/lib/task-keys.ts";

const A = "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ";
const B = "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL";

test("la sesión vale solo para su dirección y antes de caducar", () => {
  const now = 1_790_000_000_000;
  const s = { token: "t", address: A, expires_at: now / 1000 + 60 };
  assert.equal(sessionIsValid(s, A, now), true);
  assert.equal(sessionIsValid(s, B, now), false);               // otra wallet conectada
  assert.equal(sessionIsValid(s, A, now + 61_000), false);      // caducada
  assert.equal(sessionIsValid(null, A, now), false);
  assert.equal(sessionIsValid(s, null, now), false);
});

test("habilidades: sin vacíos ni repetidos", () => {
  assert.deepEqual(parseSkills("Python, FastAPI, python , , Stellar"), ["Python", "FastAPI", "Stellar"]);
  assert.deepEqual(parseSkills(""), []);
});

test("límites del perfil", () => {
  assert.equal(profileProblem("Ana", ["Python"], "Hola"), null);
  assert.match(profileProblem("x".repeat(MAX_NAME + 1), [], ""), /nombre/);
  assert.match(profileProblem("", Array.from({ length: 9 }, (_, i) => `h${i}`), ""), /8 habilidades/);
  assert.match(profileProblem("", ["x".repeat(MAX_SKILL + 1)], ""), /habilidad/);
  assert.match(profileProblem("", [], "x".repeat(MAX_BIO + 1)), /bio/);
});

test("«Limpiar lista» no borra las sesiones de identidad", () => {
  assert.deepEqual(taskStorageKeys([`cumpleycobra:sesion:${A}`, "cumpleycobra:cliente:tareas"]), ["cumpleycobra:cliente:tareas"]);
});
