// Recalcular el rules_hash en el navegador (src/lib/acuerdo.ts) da lo mismo que backend/hashing.py.
// Los hashes esperados salen del backend de Python con los mismos datos.

import assert from "node:assert/strict";
import { test } from "node:test";

import { canonicalJson, rulesHashLocal } from "../src/lib/acuerdo.ts";

test("JSON canónico: claves ordenadas, sin espacios, decimales rechazados", () => {
  assert.equal(canonicalJson({ b: 1, a: [true, null, "x"] }), '{"a":[true,null,"x"],"b":1}');
  assert.throws(() => canonicalJson({ monto: 1.5 }));
});

test("rules_hash v1 (lectura)", async () => {
  const t = {"task_id": "abc", "description": "Implementar en Python la funci\u00f3n aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una funci\u00f3n llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida est\u00e1 redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vac\u00eda devuelve una lista vac\u00eda.", "No importa ning\u00fan m\u00f3dulo (sin dependencias externas).", "La funci\u00f3n termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}]};
  assert.equal(await rulesHashLocal(t), "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96");
});

test("rules_hash v2 con NFC, escapes y dependencias desordenadas", async () => {
  const t = {"task_id": "abc", "description": "Cafe\u0301 \u00f1and\u00fa \u2028 \"comillas\" \\ tab\t \u0001 \ud83d\ude00", "criteria": ["Define una funci\u00f3n llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida est\u00e1 redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vac\u00eda devuelve una lista vac\u00eda.", "No importa ning\u00fan m\u00f3dulo (sin dependencias externas).", "La funci\u00f3n termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": ["zeta", "alfa"], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "verification": "execution", "interface": {"language": "python", "symbols": [{"module": "solucion", "name": "f", "kind": "function", "signature": "f(x)", "description": null}]}};
  assert.equal(await rulesHashLocal(t), "467bf0feb5e46ce719373d88add7623d32445ada9c60ccb8f82b0d50350f384b");
});

test("rules_hash v2 web", async () => {
  const t = {"task_id": "abc", "description": "Implementar en Python la funci\u00f3n aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una funci\u00f3n llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida est\u00e1 redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vac\u00eda devuelve una lista vac\u00eda.", "No importa ning\u00fan m\u00f3dulo (sin dependencias externas).", "La funci\u00f3n termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "verification": "execution", "interface": null, "web": {"pages": ["/", "/precios"]}};
  assert.equal(await rulesHashLocal(t), "471bd58eaba56f23e133701dace4d75993783a3f56dd44aa32e8957b550b5400");
});

test("rules_hash v3 de un hito", async () => {
  const t = {"task_id": "abc", "description": "Implementar en Python la funci\u00f3n aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["otro"], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}]};
  const hito = { indice: 1, de: 3, titulo: "Hito \u00f1", criteria: ["Define una funci\u00f3n llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida est\u00e1 redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vac\u00eda devuelve una lista vac\u00eda.", "No importa ning\u00fan m\u00f3dulo (sin dependencias externas).", "La funci\u00f3n termina para cualquier lista de entrada (sin bucles infinitos)."] };
  assert.equal(await rulesHashLocal(t, hito), "bbfcc7caa474f24bf9310cef5973ba2497cd30808b530da81e30c066646c4b0d");
});
