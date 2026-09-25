// Capturas de la fase 4b en el navegador, con las wallets Pollar de la fase 3:
//   cliente: monto en pesos -> crear -> depositar con Pollar;
//   programador: aceptar -> caso B con enlace de video -> rechazo -> consentimiento de esa entrega;
//   cliente: veredicto con video y código compartido con consentimiento.
// No aprueba manualmente: el depósito vuelve al cliente con timeout_refund al vencer el plazo.
//
// Uso (desde frontend/, con backend en :8000 y frontend en :3000 y sesiones de Pollar ya iniciadas):
//   node scripts/fase4b-capturas.mjs
// CYC_VIDEO_URL es el enlace de Drive del video demo (por defecto, uno con formato válido sin archivo real).

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
const VIDEO = process.env.CYC_VIDEO_URL ?? "https://drive.google.com/file/d/1CumpleYCobraDemo4b/view";
const MONTO_MXN = "10";
const PLAZO_MIN = "5";
mkdirSync(IMG, { recursive: true });

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const wait = (page, fn, timeout, ...args) => page.waitForFunction(fn, { polling: 500, timeout }, ...args);

async function clickText(page, selector, text, timeout = 30000) {
  await wait(page, (s, t) => [...document.querySelectorAll(s)].some((e) => e.textContent.trim().startsWith(t) && !e.disabled), timeout, selector, text);
  await page.evaluate((s, t) => [...document.querySelectorAll(s)].find((e) => e.textContent.trim().startsWith(t) && !e.disabled).click(), selector, text);
}

async function fill(page, selector, value) {
  await page.focus(selector);
  await page.keyboard.down("Control");
  await page.keyboard.press("KeyA");
  await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  await page.type(selector, value);
  const got = await page.$eval(selector, (e) => e.value);
  if (got !== value) throw new Error(`${selector}: se esperaba «${value}» y quedó «${got}»`);
}

// El campo del video llegó vacío una vez justo después de elegir el caso: se reintenta y se
// comprueba de nuevo inmediatamente antes de enviar.
async function fillStable(page, selector, value) {
  for (let i = 1; i <= 3; i++) {
    try {
      await fill(page, selector, value);
      await sleep(1500);
      if ((await page.$eval(selector, (e) => e.value)) === value) return;
    } catch (e) {
      if (i === 3) throw e;
    }
    log(`${selector}: reintento ${i}`);
  }
  throw new Error(`${selector}: el valor no se conservó`);
}

async function shot(page, name) {
  await sleep(800);
  await page.screenshot({ path: path.join(IMG, name), fullPage: true });
  log("captura", `docs/fases/img/${name}`);
}

// Igual que en fase3-hito.mjs: Chrome normal con perfil propio; el script solo se conecta.
async function open(role, x, port) {
  const proc = spawn(CHROME, [
    `--user-data-dir=${path.join(PERFILES, role)}`,
    `--remote-debugging-port=${port}`,
    `--window-position=${x},0`,
    "--window-size=960,1000",
    "--no-first-run",
    "--no-default-browser-check",
    "--lang=es-MX",
    `${APP}/cliente`,
  ], { detached: true, stdio: "ignore" });
  proc.unref();
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (r.ok) break;
    } catch { /* todavía arrancando */ }
    await sleep(500);
  }
  const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${port}`, defaultViewport: null, protocolTimeout: 600000 });
  const pages = await browser.pages();
  const page = pages.find((pg) => pg.url().startsWith(APP)) ?? pages[0] ?? (await browser.newPage());
  page.on("pageerror", (e) => log(`[${role}] error en la página:`, e.message));
  return { browser, page };
}

// Desde la fase 4a, la revisión de USDC de /cliente aparece en el paso 3, después de cargar un pedido.
async function walletReady(page, role) {
  await page.bringToFront();
  log(`[${role}] revisando la sesión de Pollar y la trustline…`);
  await page.goto(`${APP}/cliente`, { waitUntil: "load" });
  await clickText(page, "button", "Usar la plantilla de la demo", 60000);
  await wait(page, () => document.querySelector('[data-testid="saldo-usdc"],[data-testid="activar-usdc"]'), 120000);
  if (await page.$('[data-testid="activar-usdc"]')) throw new Error(`[${role}] la wallet no tiene trustline de USDC`);
  return page.$eval('[data-testid="saldo-usdc"]', (e) => ({ address: e.getAttribute("data-address"), units: Number(e.getAttribute("data-units")) }));
}

const cliente = await open("cliente", 0, 9331);
const programador = await open("programador", 960, 9332);
const summary = { video_url_enviado: VIDEO };
try {
  const wc = await walletReady(cliente.page, "cliente");
  const wp = await walletReady(programador.page, "programador");
  if (wc.address === wp.address) throw new Error("Cliente y programador tienen la misma wallet.");
  summary.cliente = wc.address;
  summary.programador = wp.address;

  // ----- Cliente: monto en pesos y depósito ----------------------------------------------------
  const c = cliente.page;
  await c.bringToFront();
  await c.goto(`${APP}/cliente`, { waitUntil: "load" });
  await clickText(c, "button", "Usar la plantilla de la demo", 60000);
  await wait(c, () => document.querySelector("#monto"), 30000);
  await fill(c, "#monto", MONTO_MXN);
  await fill(c, "#plazo", PLAZO_MIN);
  await wait(c, () => /≈ \$[\d.,]+ MXN/.test(document.body.innerText) && /tipo de cambio de referencia del/.test(document.body.innerText), 30000);
  summary.fx = await (await fetch(`${API}/fx/usd-mxn`)).json();
  await shot(c, "fase-4b-01-cliente-monto-en-pesos.png");

  await clickText(c, "button", "Crear tarea");
  await wait(c, () => location.search.includes("tarea="), 30000);
  const taskId = new URL(c.url()).searchParams.get("tarea");
  const invite = await c.$eval("code[data-value*='invitacion=']", (e) => e.getAttribute("data-value"));
  summary.task_id = taskId;
  log("tarea", taskId);
  await clickText(c, '[data-testid="depositar"]', "Depositar", 60000);
  await wait(c, () => /Depósito confirmado en la red:\s*[0-9a-f]{64}|Depósito: (?!firmando)/.test(document.body.innerText), 180000);
  summary.deposit = (await c.evaluate(() => document.body.innerText)).match(/Depósito confirmado en la red:\s*([0-9a-f]{64})/)?.[1];
  if (!summary.deposit) throw new Error("El depósito no se confirmó");
  log("deposit", summary.deposit);
  await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Depositada"), 60000);
  summary.onchain_amount = (await (await fetch(`${API}/tasks/${taskId}`)).json()).onchain?.amount;

  // ----- Programador: caso B con video, rechazo y consentimiento -------------------------------
  const p = programador.page;
  await p.bringToFront();
  await p.goto(invite, { waitUntil: "load" });
  await clickText(p, '[data-testid="aceptar"]', "Acepto los criterios", 120000);
  await wait(p, () => document.body.innerText.includes("Entregar código"), 30000);
  await clickText(p, "button", "Caso B");
  await wait(p, () => document.querySelector('[data-testid="plazo"]')?.textContent.match(/\d\d:\d\d/), 30000);
  await sleep(2000);
  await fillStable(p, "#video-demo", VIDEO);
  if ((await p.$eval("#video-demo", (e) => e.value)) !== VIDEO) throw new Error("El enlace del video no quedó en el campo");
  await clickText(p, '[data-testid="enviar"]', "Enviar");
  await wait(p, () => /Sin pago|Transacción [0-9a-f]{64}|Error /.test(document.querySelector('[data-testid="terminal"]')?.textContent ?? ""), 180000);
  await wait(p, () => document.body.innerText.includes("Revisión del cliente"), 30000);
  await shot(p, "fase-4b-02-programador-rechazo-y-consentimiento.png");

  await p.evaluate(() => [...document.querySelectorAll("label")].find((l) => l.textContent.includes("Entiendo que el cliente"))?.querySelector("input")?.click());
  await clickText(p, "button", "Autorizar revisión de este código");
  await wait(p, () => document.body.innerText.includes("Autorizaste compartir esta entrega"), 30000);
  await shot(p, "fase-4b-03-programador-consentimiento-dado.png");
  const view = await (await fetch(`${API}/tasks/${taskId}`)).json();
  summary.latest_code_hash = view.latest_code_hash;
  summary.consented_code_hash = view.consented_code_hash;

  // ----- Cliente: veredicto con video y código compartido --------------------------------------
  await c.bringToFront();
  await c.reload({ waitUntil: "load" });
  await wait(c, () => document.querySelector('[data-testid="veredictos"]')?.innerText.includes("Rechazado"), 60000);
  await clickText(c, "button", "Ver código", 60000);
  await wait(c, () => /Entrega: [0-9a-f]{64}/.test(document.body.innerText), 30000);
  summary.delivery_code_hash = (await c.evaluate(() => document.body.innerText)).match(/Entrega: ([0-9a-f]{64})/)?.[1];
  // Un reproductor en el veredicto y otro en la entrega compartida.
  summary.botones_video = await c.evaluate(() => [...document.querySelectorAll("button")].filter((b) => b.textContent.includes("Ver video demo")).length);
  // Abre el reproductor de Drive del veredicto (el de la entrega queda cerrado).
  await clickText(c, "button", "Ver video demo");
  await wait(c, () => document.querySelector("iframe[src^='https://drive.google.com/file/d/']"), 30000);
  summary.iframe_src = await c.$eval("iframe[src^='https://drive.google.com/file/d/']", (e) => e.src);
  await sleep(5000);
  await shot(c, "fase-4b-04-cliente-video-y-codigo-consentido.png");
  // La captura de página completa deja en blanco el iframe de otro origen: el reproductor se
  // captura aparte, en la ventana visible.
  const player = await c.$("iframe[src^='https://drive.google.com/file/d/']");
  await player.scrollIntoView();
  await sleep(3000);
  await player.screenshot({ path: path.join(IMG, "fase-4b-04b-reproductor-drive.png") });
  log("captura", "docs/fases/img/fase-4b-04b-reproductor-drive.png");
  summary.ok = summary.delivery_code_hash === summary.consented_code_hash && summary.consented_code_hash === summary.latest_code_hash;
} finally {
  writeFileSync(path.join(ROOT, "scripts", ".logs", "fase4b-capturas.json"), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary, null, 1));
  await cliente.browser.disconnect();
  await programador.browser.disconnect();
}
