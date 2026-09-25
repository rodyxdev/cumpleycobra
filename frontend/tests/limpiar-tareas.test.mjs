// «Limpiar lista»: solo se borran las llaves de tareas, nunca la sesión de Pollar.

import assert from "node:assert/strict";
import { test } from "node:test";

import { taskStorageKeys } from "../src/lib/task-keys.ts";

test("limpiar lista borra solo las llaves de tareas", () => {
  const all = [
    "cumpleycobra:cliente:tareas",
    "cumpleycobra:cliente:pEK6BPUCe1YvYSDZ",
    "cumpleycobra:programador:pEK6BPUCe1YvYSDZ",
    "cumpleycobra:direccion:cliente",   // última dirección usada: no es una tarea
    "pollar:session",                   // sesión de Pollar (cualquier llave ajena)
    "pollar_auth_token",
    "otra-app:cliente:x",
  ];
  assert.deepEqual(taskStorageKeys(all), [
    "cumpleycobra:cliente:tareas",
    "cumpleycobra:cliente:pEK6BPUCe1YvYSDZ",
    "cumpleycobra:programador:pEK6BPUCe1YvYSDZ",
  ]);
});
