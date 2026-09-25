// Identidad verificada en el navegador, con las dos wallets Pollar:
//   programador: «Verificar identidad» (SEP-10 firmado por Pollar) y edición de su perfil;
//   cliente: la tarjeta de calificación pide verificar, se verifica y se califica la tarea pagada.
// Captura cada paso en docs/img/identidad-*.png.
//
// Uso (desde frontend/, con backend en :8000, frontend en :3000 y sesiones de Pollar iniciadas):
//   node scripts/identidad-capturas.mjs [TASK_ID]   (por defecto, la tarea del último ensayo)

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const FRONT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(FRONT, "..");
const IMG = path.join(ROOT, "docs", "img");
const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const PROGRAMADOR = "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ";
const PERFIL = {
  nombre: "Rodrigo Martínez",
  habilidades: "Python, FastAPI, Stellar, Automatización",
  bio: "Scripts de Python verificables: cumplo los criterios acordados y cobro en Stellar.",
};
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

async function fill(page, selector, value) {
  await page.bringToFront();
  await page.focus(selector);
  await page.keyboard.down("Control"); await page.keyboard.press("KeyA"); await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  await page.type(selector, value);
  if ((await page.$eval(selector, (e) => e.value)) !== value) throw new Error(`${selector}: el valor no quedó escrito`);
}

async function tab(port) {
  const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${port}`, defaultViewport: null, protocolTimeout: 300000 });
  return { browser, page: await browser.newPage() }; // pestaña propia y visible
}

const summary = { task_id: taskId };
const prog = await tab(9332);
const cli = await tab(9331);
try {
  // ----- Programador: verificar identidad desde el encabezado ------------------------------------
  const p = prog.page;
  await p.bringToFront();
  await p.goto(`${APP}/programador/${PROGRAMADOR}`, { waitUntil: "load" });
  await wait(p, () => document.querySelector('header [data-testid="verificar-identidad"], header [data-testid="identidad-verificada"]'), 60000);
  if (await p.$('header [data-testid="identidad-verificada"]')) throw new Error("El programador ya tenía sesión: borra cumpleycobra:sesion:* para repetir");
  await shot(p, "identidad-01-programador-sin-verificar.png", "header");
  await shot(p, "identidad-02-perfil-pide-verificar.png", '[data-testid="perfil-requiere-identidad"]');
  await p.click('header [data-testid="verificar-identidad"]');
  await wait(p, () => document.querySelector('header [data-testid="identidad-verificada"]') || document.querySelector('header [role="alert"]'), 60000);
  if (await p.$('header [role="alert"]')) throw new Error(await p.$eval('header [role="alert"]', (e) => e.textContent));
  summary.programador_verificado = true;
  await shot(p, "identidad-03-programador-verificado.png", "header");

  // ----- Programador: editar su perfil ------------------------------------------------------
  await wait(p, () => document.querySelector('[data-testid="editar-perfil"]'), 30000);
  await fill(p, "#perfil-nombre", PERFIL.nombre);
  await fill(p, "#perfil-habilidades", PERFIL.habilidades);
  await fill(p, "#perfil-bio", PERFIL.bio);
  await p.click('[data-testid="guardar-perfil"]');
  await wait(p, () => document.querySelector('[data-testid="perfil-guardado"]') || document.querySelector('[data-testid="editar-perfil"] [role="alert"]'), 30000);
  await p.reload({ waitUntil: "load" });
  await wait(p, (n) => document.querySelector('[data-testid="perfil-nombre"]')?.textContent === n, 60000, PERFIL.nombre);
  summary.perfil_api = await (await fetch(`${API}/programadores/${PROGRAMADOR}`)).json().then((j) =>
    ({ nombre: j.nombre, habilidades: j.habilidades, bio: j.bio, identidad_verificada: j.identidad_verificada }));
  await shot(p, "identidad-04-perfil-editado.png");

  // ----- Cliente: calificar pide verificar; se verifica y se califica -----------------------------
  const c = cli.page;
  await c.bringToFront();
  await c.goto(`${APP}/cliente?tarea=${encodeURIComponent(taskId)}`, { waitUntil: "load" });
  await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Pagada"), 60000);
  await wait(c, () => document.querySelector('[data-testid="calificar-requiere-identidad"]'), 30000);
  await c.$eval('[data-testid="calificar"]', (e) => e.scrollIntoView({ block: "center" }));
  await shot(c, "identidad-05-calificar-pide-identidad.png", '[data-testid="calificar"]');
  // Sin sesión, el backend rechaza aunque se tenga el X-Client-Token.
  const noSession = await c.evaluate(async (id) => {
    const ct = JSON.parse(localStorage.getItem(`cumpleycobra:cliente:${id}`)).client_token;
    const r = await fetch(`http://localhost:8000/tasks/${id}/calificacion`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Client-Token": ct }, body: JSON.stringify({ estrellas: 1 }) });
    return (await r.json()).error;
  }, taskId);
  summary.sin_sesion = noSession;

  await c.click('[data-testid="calificar"] [data-testid="verificar-identidad"]');
  await wait(c, () => document.querySelector('[data-testid="estrella-4"]') || document.querySelector('[data-testid="calificar"] [role="alert"]'), 60000);
  if (!(await c.$('[data-testid="estrella-4"]'))) throw new Error(await c.$eval('[data-testid="calificar"] [role="alert"]', (e) => e.textContent));
  summary.cliente_verificado = !!(await c.$('header [data-testid="identidad-verificada"]'));
  await c.click('[data-testid="estrella-4"]');
  await fill(c, "#comentario", "Entregó lo acordado; la verificación de identidad deja claro quién califica.");
  await c.click('[data-testid="enviar-calificacion"]');
  await wait(c, () => /Calificaste con 4 de 5 estrellas/.test(document.querySelector('[data-testid="calificar"]')?.innerText ?? ""), 30000);
  await c.$eval('[data-testid="calificar"]', (e) => e.scrollIntoView({ block: "center" }));
  await shot(c, "identidad-06-calificada-con-sesion.png", '[data-testid="calificar"]');
  summary.rating = (await (await fetch(`${API}/tasks/${encodeURIComponent(taskId)}`)).json()).rating;
  await shot(c, "identidad-07-cliente-verificado.png", "header");

  // ----- Lista de programadores con nombre y habilidades ----------------------------------------------
  await c.goto(`${APP}/programadores`, { waitUntil: "load" });
  await wait(c, () => document.querySelector('[data-testid="lista-programadores"] [data-testid="habilidades"]'), 60000);
  summary.lista = await c.$$eval('[data-testid="lista-programadores"] > li', (li) => li.map((e) => e.innerText.replace(/\s+/g, " ").slice(0, 200)));
  await shot(c, "identidad-08-lista.png");
} finally {
  writeFileSync(path.join(ROOT, "scripts", ".logs", "identidad-capturas.json"), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary, null, 1));
  for (const t of [prog, cli]) { await t.page.close(); await t.browser.disconnect(); }
}
