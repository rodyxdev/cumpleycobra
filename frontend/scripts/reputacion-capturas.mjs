// Califica la tarea del último ensayo (scripts/.logs/fase5-ensayo.json) desde el navegador del cliente
// y captura la tarjeta, el perfil del programador y la lista de programadores.
//
// Uso (desde frontend/, con backend en :8000, frontend en :3000 y la sesión de Pollar del cliente):
//   node scripts/reputacion-capturas.mjs [TASK_ID]

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const FRONT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(FRONT, "..");
const IMG = path.join(ROOT, "docs", "img");
const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const COMMENT = "Cumplió los criterios acordados y el pago salió solo. Lo volvería a contratar.";
const taskId = process.argv[2] ?? JSON.parse(readFileSync(path.join(ROOT, "scripts", ".logs", "fase5-ensayo.json"), "utf8")).task_id;

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const wait = (page, fn, timeout, ...args) => page.waitForFunction(fn, { polling: 200, timeout }, ...args);

async function shot(page, name, selector) {
  await sleep(1200);
  const target = selector ? await page.$(selector) : null;
  await (target ?? page).screenshot({ path: path.join(IMG, name), ...(target ? {} : { fullPage: true }) });
  log("captura", `docs/img/${name}`);
}

const browser = await puppeteer.connect({ browserURL: "http://127.0.0.1:9331", defaultViewport: null, protocolTimeout: 300000 });
const c = await browser.newPage(); // pestaña propia y visible: Chrome descarta teclas en pestañas ocultas
const summary = { task_id: taskId };
try {
  await c.goto(`${APP}/cliente?tarea=${encodeURIComponent(taskId)}`, { waitUntil: "load" });
  await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Pagada"), 60000);
  await wait(c, () => document.querySelector('[data-testid="calificar"]'), 30000);
  await c.$eval('[data-testid="calificar"]', (e) => e.scrollIntoView({ block: "center" }));
  await shot(c, "reputacion-01-califica.png", '[data-testid="calificar"]');

  await c.click('[data-testid="estrella-5"]');
  await c.bringToFront();
  await c.focus("#comentario");
  await c.type("#comentario", COMMENT);
  if ((await c.$eval("#comentario", (e) => e.value)) !== COMMENT) throw new Error("El comentario no quedó escrito");
  await c.click('[data-testid="enviar-calificacion"]');
  await wait(c, () => /Calificaste con 5 de 5 estrellas/.test(document.querySelector('[data-testid="calificar"]')?.innerText ?? ""), 30000);
  await shot(c, "reputacion-02-calificada.png", '[data-testid="calificar"]');
  summary.rating = (await (await fetch(`${API}/tasks/${encodeURIComponent(taskId)}`)).json()).rating;

  // Con un token ajeno el backend rechaza la calificación (INVALID_TOKEN). ALREADY_RATED y los demás
  // errores se prueban en backend/tests/test_reputacion.py.
  const again = await fetch(`${API}/tasks/${encodeURIComponent(taskId)}/calificacion`, {
    method: "POST", headers: { "content-type": "application/json", "X-Client-Token": "token-equivocado" },
    body: JSON.stringify({ estrellas: 1 }),
  });
  summary.token_equivocado = (await again.json()).error;

  await c.click('[data-testid="perfil-programador"]');
  await wait(c, () => location.pathname.startsWith("/programador/") && document.querySelector('[data-testid="historial"]'), 60000);
  summary.perfil = c.url().replace(APP, "");
  summary.metricas = await c.evaluate(() => Object.fromEntries(["motor", "manual", "clientes", "calificacion"].map((k) =>
    [k, document.querySelector(`[data-testid="metrica-${k}"] dd`)?.innerText.replace(/\s+/g, " ")])));
  summary.nota = await c.$eval('[data-testid="nota-honesta"]', (e) => e.innerText);
  summary.enlaces_explorador = await c.$$eval('[data-testid="historial"] a[href*="stellar.expert"]', (as) => as.length);
  await shot(c, "reputacion-03-perfil.png");

  await c.click('a[href="/programadores"]');
  await wait(c, () => location.pathname === "/programadores" && document.querySelector('[data-testid="lista-programadores"]'), 60000);
  summary.lista = await c.$$eval('[data-testid="lista-programadores"] > li', (li) => li.map((e) => e.innerText.replace(/\s+/g, " ").slice(0, 160)));
  await shot(c, "reputacion-04-lista.png");
} finally {
  writeFileSync(path.join(ROOT, "scripts", ".logs", "reputacion-capturas.json"), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary, null, 1));
  await c.close();
  await browser.disconnect();
}
