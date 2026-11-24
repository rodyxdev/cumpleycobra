import assert from "node:assert/strict";
import { test } from "node:test";
import { buildInterface, guessInterface, interfaceProblem, isFinal, parsePages, parseRepo, progressLines, zipSource } from "../src/lib/verification.ts";

test("propone la interfaz desde la firma de la descripción", () => {
  const spec = {
    description: "Implementar en Python la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve…",
    criteria: [],
  };
  assert.deepEqual(guessInterface(spec), {
    module: "descuentos", name: "aplicar_descuento",
    signature: "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]",
  });
  assert.equal(guessInterface({ description: "Módulo que resume_ventas(texto: str)", criteria: [] }).module, "ventas");
  assert.deepEqual(guessInterface({ description: "Sin firma", criteria: [] }), { module: "solucion", name: "", signature: "" });
});

test("no confunde prosa entre paréntesis con una firma", () => {
  const vacio = { module: "solucion", name: "", signature: "" };
  assert.deepEqual(guessInterface({ description: "Recibe una lista de precios (números) y un porcentaje.", criteria: [] }), vacio);
  assert.deepEqual(guessInterface({ description: "Devuelve los precios(números) en orden.", criteria: [] }), vacio);
  // La primera firma real gana aunque antes haya prosa con paréntesis.
  assert.equal(guessInterface({ description: "Lista de precios (números).", criteria: ["Define f(x: int) -> int."] }).name, "f");
});

test("la interfaz solo acepta nombres de Python y una firma que empiece con la función", () => {
  assert.equal(interfaceProblem("descuentos", "aplicar_descuento", "aplicar_descuento(p)"), null);
  assert.match(interfaceProblem("mi-modulo", "f", "f()"), /módulo/);
  assert.match(interfaceProblem("m", "f x", "f()"), /función/);
  assert.match(interfaceProblem("m", "f", "g()"), /firma/);
  assert.deepEqual(buildInterface(" m ", " f ", " f() "), { language: "python", symbols: [{ module: "m", name: "f", kind: "function", signature: "f()" }] });
});

test("repositorio público con SHA completo, también desde la URL de GitHub", () => {
  const sha = "a".repeat(40);
  assert.deepEqual(parseRepo("owner/repo", sha), { repo: "owner/repo", sha });
  assert.deepEqual(parseRepo(`https://github.com/owner/repo/tree/${sha.toUpperCase()}`, ""), { repo: "owner/repo", sha });
  assert.match(parseRepo("owner/repo", "main"), /SHA completo/);
  assert.match(parseRepo("no es repo", sha), /owner\/nombre/);
});

test("el ZIP viaja en base64 y respeta el tamaño máximo", async () => {
  const bytes = new Uint8Array([80, 75, 3, 4, 255]);
  const file = { size: bytes.length, arrayBuffer: async () => bytes.buffer };
  assert.deepEqual(await zipSource(file), { kind: "zip", zip_b64: Buffer.from(bytes).toString("base64") });
  assert.match(await zipSource({ size: 3 * 1024 * 1024, arrayBuffer: async () => new ArrayBuffer(0) }), /2 MB/);
});

test("las líneas de avance salen de los eventos reales, con su segundo", () => {
  const lines = progressLines({ created_at: 100, progress: [
    { stage: "ingesta", label: "Obteniendo la entrega", detail: "", at: 101.5 },
    { stage: "tests", label: "Corriendo la suite oculta", detail: "corriendo la suite oculta", at: 104 },
  ] });
  assert.deepEqual(lines.map((l) => [l.text, l.seconds]), [
    ["Obteniendo la entrega", 1.5], ["Corriendo la suite oculta: corriendo la suite oculta", 4],
  ]);
  assert.equal(isFinal({ status: "running" }), false);
  assert.equal(isFinal({ status: "failed" }), true);
});

test("parsePages acepta rutas del sitio y rechaza las inválidas", () => {
  assert.deepEqual(parsePages("/, /contacto\n/precios"), ["/", "/contacto", "/precios"]);
  assert.match(parsePages(""), /al menos una/);
  assert.match(parsePages("contacto"), /no es una ruta válida/);
  assert.match(parsePages("/../etc"), /no es una ruta válida/);
  assert.match(parsePages("/, /"), /repetidas/);
  assert.match(parsePages("/a,/b,/c,/d,/e,/f"), /Máximo 5/);
});

test("el motivo de cierre dice si la tarea se pagó o se reembolsó", async () => {
  const { closedReason } = await import("../src/lib/format.ts");
  assert.match(closedReason("Released"), /ya se pagó/);
  assert.match(closedReason("Refunded"), /volvió al cliente/);
  assert.match(closedReason(undefined), /todavía no deposita/);
});
