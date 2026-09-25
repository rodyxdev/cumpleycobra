// Prueba de navegador del pedido asistido, sin wallet ni transacciones.
// Backend nuevo en :8001, frontend con NEXT_PUBLIC_API_URL=http://localhost:8001 en :3001.
// Ejecutar después de probar_pedido.py para no compartir su cuota de Vertex.
// Desde frontend: node scripts/fase4a-ui.mjs
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const images = path.join(root, "docs/fases/img");
mkdirSync(images, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
  userDataDir: path.join(root, ".pytest_cache/fase4a-browser"),
  args: ["--no-first-run", "--no-default-browser-check", "--lang=es-MX"],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.setViewport({ width: 1280, height: 1000, deviceScaleFactor: 1 });
page.setDefaultTimeout(90000);

async function click(text) {
  await page.waitForFunction((label) => [...document.querySelectorAll("button")].some((b) => b.textContent.trim() === label && !b.disabled), {}, text);
  await page.evaluate((label) => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === label && !b.disabled).click(), text);
}

async function fill(selector, value) {
  await page.$eval(selector, (element, text) => {
    const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(element, text);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

try {
  await page.goto("http://localhost:3001/cliente", { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.querySelector("#pedido-original")?.value.includes("redondeados a 2 decimales"));
  assert.equal(await page.$eval("#pedido-original", (e) => e.maxLength), 2000);
  await page.screenshot({ path: path.join(images, "fase-4a-01-pedido-original.png"), fullPage: true });
  const draftResponse = page.waitForResponse((r) => r.url().endsWith("/tasks/draft") && r.request().method() === "POST");
  await click("Pídele a la IA que mejore tu pedido");
  const response = await draftResponse;
  assert.equal(response.status(), 200, await response.text());
  const draft = await response.json();
  await page.waitForSelector("#descripcion");
  assert.equal(await page.$eval("#descripcion", (e) => e.value), draft.description);
  assert.equal((await page.$$("textarea[id^='criterio-']")).length, draft.criteria.length);

  // Revisión real: introducir un criterio vago, verificar su marca y aplicar la sugerencia.
  await fill("#criterio-0", "Que sea rápido");
  await new Promise((resolve) => setTimeout(resolve, 8000));
  const reviewResponse = page.waitForResponse((r) => r.url().endsWith("/tasks/draft/review") && r.request().method() === "POST");
  await click("Revisar criterios");
  const reviewedResponse = await reviewResponse;
  assert.equal(reviewedResponse.status(), 200, await reviewedResponse.text());
  const review = await reviewedResponse.json();
  assert.equal(review.criteria.length, draft.criteria.length);
  assert.equal(review.criteria[0].vague, true);
  await page.waitForFunction(() => document.body.innerText.includes("Criterio vago"));
  await page.waitForFunction(() => document.querySelector("#criterio-0")?.disabled === false);
  await new Promise((resolve) => setTimeout(resolve, 250)); // terminar las transiciones visuales
  await page.screenshot({ path: path.join(images, "fase-4a-02-version-editable.png"), fullPage: true });
  await click("Aplicar sugerencia");
  assert.equal(await page.$eval("#criterio-0", (e) => e.value), review.criteria[0].suggestion);
  assert.equal(await page.$("[role='status']"), null);

  // Ediciones y límites sin gastar cuota adicional.
  await fill("#descripcion", "Descripción final editada por el cliente.");
  if (!draft.examples.length) await click("Agregar ejemplo");
  await fill("#ejemplo-0-input", "precios=[20], porcentaje=10");
  await fill("#ejemplo-0-output", "[18.0]");
  assert.equal(await page.$eval("#ejemplo-0-output", (e) => e.value), "[18.0]");
  await click("Agregar criterio");
  assert.equal((await page.$$("textarea[id^='criterio-']")).length, draft.criteria.length + 1);
  await page.click(`[aria-label="Quitar criterio ${draft.criteria.length + 1}"]`);
  assert.equal((await page.$$("textarea[id^='criterio-']")).length, draft.criteria.length);
  assert.equal(await page.$eval("#criterio-0", (e) => e.maxLength), 300);

  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: path.join(images, "fase-4a-03-movil.png"), fullPage: true });

  // Fallo controlado solo del endpoint de borrador para comprobar el respaldo.
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if (request.url().endsWith("/tasks/draft") && request.method() === "POST") {
      request.respond({ status: 502, contentType: "application/json", headers: { "access-control-allow-origin": "http://localhost:3001" },
        body: JSON.stringify({ error: "ENGINE_UNAVAILABLE", message: "No se pudo preparar el pedido. Usa la plantilla de la demo." }) });
    } else request.continue();
  });
  await click("Pídele a la IA que mejore tu pedido");
  await page.waitForSelector("[role='alert']");
  assert.equal(await page.$eval("#descripcion", (e) => e.value), "Descripción final editada por el cliente.");
  await click("Usar la plantilla de la demo");
  assert.equal((await page.$$("textarea[id^='criterio-']")).length, 6);
  assert.equal(await page.$("[role='alert']"), null);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  writeFileSync(path.join(root, "docs/fases/fase-4a-ui.json"), JSON.stringify({
    captured_at: new Date().toISOString(), draft, review, browser_errors: errors,
    checks: ["borrador real", "revisión real", "aplicar sugerencia", "invalidar revisión al editar", "editar descripción y ejemplos",
      "agregar y quitar criterios", "límites HTML", "móvil sin desbordamiento", "conservar ediciones tras error", "plantilla de respaldo"],
  }, null, 2));
  console.log("UI: 10 comprobaciones correctas; 3 capturas; sin crear tareas ni transacciones.");
  console.log("Errores de navegador:", JSON.stringify(errors));
} finally {
  await browser.close();
}
