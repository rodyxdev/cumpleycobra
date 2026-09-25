// Ensayo completo de la demo (docs/demo.md) en el navegador, con Pollar y el pedido asistido:
//   pedido -> mejorar con IA -> revisar criterios -> crear -> depositar -> aceptar ->
//   caso C rechazado -> caso A pagado. Mide cada paso desde el clic hasta que la pantalla lo muestra.
//
// Uso (desde frontend/, con backend en :8000, frontend en :3000 y sesiones de Pollar iniciadas):
//   node scripts/fase5-ensayo.mjs
// Usa pestañas nuevas y visibles: Chrome descarta las teclas enviadas a pestañas ocultas.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const FRONT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(FRONT, "..");
const IMG = path.join(ROOT, "docs", "fases", "img");
const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PERFILES = process.env.CYC_PERFILES ?? path.join(FRONT, ".perfiles");
const VIDEO = process.env.CYC_VIDEO_URL ?? "https://drive.google.com/file/d/1jg-nMazcC4Cln9eSSia5be0RsHSFizM9/view?usp=sharing";
mkdirSync(IMG, { recursive: true });

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const wait = (page, fn, timeout, ...args) => page.waitForFunction(fn, { polling: 200, timeout }, ...args);
const text = (page) => page.evaluate(() => document.body.innerText);

async function clickText(page, selector, t, timeout = 30000) {
  await wait(page, (s, x) => [...document.querySelectorAll(s)].some((e) => e.textContent.trim().startsWith(x) && !e.disabled), timeout, selector, t);
  await page.evaluate((s, x) => [...document.querySelectorAll(s)].find((e) => e.textContent.trim().startsWith(x) && !e.disabled).click(), selector, t);
}

async function fill(page, selector, value) {
  await page.bringToFront();
  if ((await page.evaluate(() => document.visibilityState)) !== "visible") throw new Error("Pestaña oculta: deja la ventana visible");
  await page.focus(selector);
  await page.keyboard.down("Control"); await page.keyboard.press("KeyA"); await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  await page.type(selector, value);
  const got = await page.$eval(selector, (e) => e.value);
  if (got !== value) throw new Error(`${selector}: se esperaba «${value}» y quedó «${got}»`);
}

async function shot(page, name) {
  await sleep(1000);
  await page.screenshot({ path: path.join(IMG, name), fullPage: true });
  log("captura", `docs/fases/img/${name}`);
}

async function open(role, x, port) {
  const proc = spawn(CHROME, [`--user-data-dir=${path.join(PERFILES, role)}`, `--remote-debugging-port=${port}`,
    `--window-position=${x},0`, "--window-size=960,1000", "--no-first-run", "--no-default-browser-check", "--lang=es-MX"],
  { detached: true, stdio: "ignore" });
  proc.unref();
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/json/version`)).ok) break; } catch { /* arrancando */ }
    await sleep(500);
  }
  const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${port}`, defaultViewport: null, protocolTimeout: 600000 });
  const page = await browser.newPage();
  page.on("pageerror", (e) => log(`[${role}] error en la página:`, e.message));
  return { browser, page };
}

// Cronómetro por paso: desde la acción hasta que la pantalla muestra el resultado.
const steps = [];
async function step(name, fn) {
  const t = Date.now();
  const extra = await fn();
  const seconds = (Date.now() - t) / 1000;
  steps.push({ name, seconds, ...(extra ?? {}) });
  log(`${name}: ${seconds.toFixed(1)} s`);
  return extra;
}

const cliente = await open("cliente", 0, 9331);
const programador = await open("programador", 960, 9332);
const c = cliente.page;
const p = programador.page;
const summary = { started_at: new Date().toISOString() };
try {
  // Preparación (no se cronometra): sesión de Pollar en ambas pestañas.
  await p.goto(`${APP}/cliente`, { waitUntil: "load" });
  await c.bringToFront();
  await c.goto(`${APP}/cliente`, { waitUntil: "load" });
  await wait(c, () => document.querySelector("#pedido-original")?.value.length > 0, 30000);
  summary.pedido = await c.$eval("#pedido-original", (e) => e.value);
  const t0 = Date.now();

  // 1. Mejorar con IA.
  const draft = await step("Pedido asistido: «Pídele a la IA que mejore tu pedido»", async () => {
    await clickText(c, "button", "Pídele a la IA que mejore tu pedido");
    await wait(c, () => document.querySelector('[data-testid="pedido-paso-2"]') || document.querySelector('[role="alert"]'), 90000);
    if (await c.$('[role="alert"]')) throw new Error(await c.$eval('[role="alert"]', (e) => e.textContent));
    return { criterios: await c.$$eval("textarea[id^='criterio-']", (els) => els.map((e) => e.value)) };
  });
  summary.draft = { description: await c.$eval("#descripcion", (e) => e.value), criterios: draft.criterios };

  // 2. Revisar criterios con «Que sea rápido» agregado; se quita después sin aplicar la sugerencia.
  await step("Revisar criterios (con «Que sea rápido» agregado)", async () => {
    const n = draft.criterios.length;
    if (n >= 8) throw new Error("El borrador ya tiene 8 criterios: no se puede agregar otro");
    await clickText(c, "button", "Agregar criterio");
    await wait(c, (i) => document.querySelector(`#criterio-${i}`), 10000, n);
    await fill(c, `#criterio-${n}`, "Que sea rápido");
    await clickText(c, "button", "Revisar criterios");
    await wait(c, () => /Revisión completada|role="alert"/.test(document.body.innerText) || document.body.innerText.includes("Revisión completada"), 90000);
    const flagged = await c.evaluate(() => [...document.querySelectorAll("p")].filter((e) => e.textContent.startsWith("Criterio vago")).map((e) => e.textContent));
    await shot(c, "fase-5-01-revision-criterio-vago.png");
    await c.evaluate((i) => document.querySelector(`[aria-label="Quitar criterio ${i + 1}"]`).click(), n);
    await wait(c, (i) => !document.querySelector(`#criterio-${i}`), 10000, n);
    return { marcados: flagged };
  });
  summary.revision = steps.at(-1).marcados;

  // 3. Crear la tarea (20 MXN, 10 minutos).
  const created = await step("Crear tarea", async () => {
    await fill(c, "#monto", "20");
    await fill(c, "#plazo", "10");
    await clickText(c, "button", "Crear tarea");
    await wait(c, () => location.search.includes("tarea="), 30000);
    await c.waitForSelector("code[data-value*='invitacion=']", { timeout: 30000 });
    return { taskId: new URL(c.url()).searchParams.get("tarea") };
  });
  const taskId = created.taskId;
  summary.task_id = taskId;
  const invite = await c.$eval("code[data-value*='invitacion=']", (e) => e.getAttribute("data-value"));

  // 4. Depositar con Pollar.
  const dep = await step("Depositar con Pollar (firma, envío y confirmación)", async () => {
    await clickText(c, '[data-testid="depositar"]', "Depositar", 60000);
    await wait(c, () => /Depósito confirmado en la red:\s*[0-9a-f]{64}|Depósito: (?!firmando)/.test(document.body.innerText), 180000);
    const tx = (await text(c)).match(/Depósito confirmado en la red:\s*([0-9a-f]{64})/)?.[1];
    if (!tx) throw new Error("El depósito no se confirmó");
    await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Depositada"), 60000);
    return { tx };
  });
  summary.deposit = dep.tx;

  // 5. Aceptar los criterios.
  await step("Programador: abrir invitación y aceptar criterios", async () => {
    await p.bringToFront();
    await p.goto(invite, { waitUntil: "load" });
    await clickText(p, '[data-testid="aceptar"]', "Acepto los criterios", 120000);
    await wait(p, () => document.body.innerText.includes("Entregar código"), 30000);
  });

  const send = async (label) => {
    await clickText(p, "button", label);
    await wait(p, () => document.querySelector('[data-testid="plazo"]')?.textContent.match(/\d\d:\d\d/), 30000);
    await clickText(p, '[data-testid="enviar"]', "Enviar");
    // Cada envío reinicia la terminal con «$ POST /evaluate · <caso>»; se espera ese encabezado y el cierre.
    await wait(p, (l) => {
      const t = document.querySelector('[data-testid="terminal"]')?.textContent ?? "";
      return t.includes(`POST /evaluate · ${l}`) && /Sin pago|Transacción [0-9a-f]{64}|Error /.test(t);
    }, 180000, label);
    const terminal = await p.$eval('[data-testid="terminal"]', (e) => e.innerText);
    return { terminal, tx: terminal.match(/Transacción ([0-9a-f]{64})/)?.[1] ?? null };
  };

  // 6. Caso C: rechazo por seguridad.
  const caseC = await step("Caso C enviado → veredicto", () => send("Caso C"));
  summary.caso_c = { rechazado: /RECHAZADO/.test(caseC.terminal), sin_pago: /Sin pago/.test(caseC.terminal) };

  // 7. Caso A con video: aprobado y pagado.
  const caseA = await step("Caso A con video enviado → veredicto y pago", async () => {
    await fill(p, "#video-demo", VIDEO);
    return send("Caso A");
  });
  summary.caso_a = { aprobado: /APROBADO/.test(caseA.terminal), release: caseA.tx };
  await shot(p, "fase-5-02-programador-caso-a-pagado.png");

  // 8. El cliente ve «Pagada» y recibe el código.
  await step("Cliente: estado «Pagada» y código entregado", async () => {
    await c.bringToFront();
    await c.reload({ waitUntil: "load" });
    await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Pagada"), 60000);
    await clickText(c, "button", "Ver código", 60000);
    await wait(c, () => /Entrega: [0-9a-f]{64}/.test(document.body.innerText), 30000);
  });
  summary.total_seconds = (Date.now() - t0) / 1000;
  log(`Total: ${summary.total_seconds.toFixed(1)} s`);
  await shot(c, "fase-5-03-cliente-pagada.png");
  summary.onchain = (await (await fetch(`${API}/tasks/${taskId}`)).json()).onchain;
} finally {
  summary.steps = steps;
  writeFileSync(path.join(ROOT, "scripts", ".logs", "fase5-ensayo.json"), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary, null, 1));
  await cliente.browser.disconnect();
  await programador.browser.disconnect();
}
