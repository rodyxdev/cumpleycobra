// Hito de la fase 3, todo en el navegador y sin CLI:
//   Tarea 1: crear -> depositar con Pollar -> aceptar con la wallet Pollar del programador -> caso A pagado.
//   Tarea 2: crear -> depositar -> aceptar -> caso B rechazado -> "Aprobar manualmente" pagado.
//
// Abre dos ventanas de Chrome VISIBLES con perfiles separados (cliente y programador). Rodrigo
// inicia sesión en Pollar en cada una (el script no toca credenciales); el resto lo hace el script.
// Los perfiles se guardan en CYC_PERFILES (por defecto frontend/.perfiles, ignorado por git), así
// que la sesión sobrevive entre corridas.
//
// Uso (desde frontend/, con backend en :8000 y frontend en :3000):
//   node scripts/fase3-hito.mjs

import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const FRONT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(FRONT, "..");
const IMG = path.join(ROOT, "docs", "fases", "img");
const APP = "http://localhost:3000";
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PERFILES = process.env.CYC_PERFILES ?? path.join(FRONT, ".perfiles");
mkdirSync(IMG, { recursive: true });

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const wait = (page, fn, timeout, ...args) => page.waitForFunction(fn, { polling: 500, timeout }, ...args);

async function clickText(page, selector, text, timeout = 30000) {
  await wait(page, (s, t) => [...document.querySelectorAll(s)].some((e) => e.textContent.trim().startsWith(t) && !e.disabled), timeout, selector, text);
  await page.evaluate((s, t) => [...document.querySelectorAll(s)].find((e) => e.textContent.trim().startsWith(t) && !e.disabled).click(), selector, text);
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(IMG, name), fullPage: true });
  log("captura", `docs/fases/img/${name}`);
}

// Chrome normal (sin banderas de automatización) con perfil propio y puerto de depuración; el
// script solo se conecta. Las ventanas lanzadas por puppeteer se quedaban en negro o se cerraban.
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
  page.on("close", () => log(`[${role}] se cerró la pestaña`));
  return { browser, page };
}

/** Espera a que la wallet esté lista: sesión iniciada y trustline de USDC (la activa si falta). */
async function walletReady(page, role) {
  await page.bringToFront();
  log(`[${role}] esperando inicio de sesión en Pollar (hazlo en la ventana "${role}")…`);
  await wait(page, () => document.querySelector('[data-testid="saldo-usdc"],[data-testid="activar-usdc"]'), 900000);
  if (await page.$('[data-testid="activar-usdc"]')) {
    log(`[${role}] falta la trustline: clic en "Activar USDC" (firma Pollar)`);
    await clickText(page, "button", "Activar USDC");
    await wait(page, () => document.querySelector('[data-testid="saldo-usdc"]'), 120000);
  }
  const info = await page.$eval('[data-testid="saldo-usdc"]', (e) => ({
    text: e.textContent, address: e.getAttribute("data-address"), units: Number(e.getAttribute("data-units")),
  }));
  log(`[${role}] ${info.text}`);
  return info;
}

async function createAndDeposit(page) {
  await page.bringToFront();
  await page.goto(`${APP}/cliente`, { waitUntil: "load" });
  await clickText(page, "button", "Usar la plantilla de la demo", 60000);
  await clickText(page, "button", "Crear tarea");
  await wait(page, () => location.search.includes("tarea="), 30000);
  const taskId = new URL(page.url()).searchParams.get("tarea");
  const invite = await page.$eval("code[data-value*='invitacion=']", (e) => e.getAttribute("data-value"));
  log("tarea", taskId);
  await clickText(page, '[data-testid="depositar"]', "Depositar", 60000);
  await wait(page, () => document.querySelector('[data-testid="tx-Depósito"]') || /Depósito: (?!firmando)/.test(document.body.innerText), 180000);
  const text = await page.evaluate(() => document.body.innerText);
  const depositTx = text.match(/Depósito confirmado en la red:\s*([0-9a-f]{64})/)?.[1];
  if (!depositTx) throw new Error("El depósito no se confirmó: " + (text.match(/Depósito: .*/)?.[0] ?? "sin mensaje"));
  log("deposit", depositTx);
  await wait(page, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Depositada"), 60000);
  return { taskId, invite, depositTx };
}

async function acceptAndSend(page, invite, caseLabel) {
  await page.bringToFront();
  await page.goto(invite, { waitUntil: "load" });
  await clickText(page, '[data-testid="aceptar"]', "Acepto los criterios", 120000);
  await wait(page, () => document.body.innerText.includes("Entregar código"), 30000);
  await clickText(page, "button", caseLabel);
  await wait(page, () => document.querySelector('[data-testid="plazo"]')?.textContent.match(/\d\d:\d\d/), 30000);
  await clickText(page, '[data-testid="enviar"]', "Enviar");
  await wait(page, () => /Sin pago|Transacción [0-9a-f]{64}|Error /.test(document.querySelector('[data-testid="terminal"]')?.textContent ?? ""), 180000);
  await sleep(1500);
  const terminal = await page.$eval('[data-testid="terminal"]', (e) => e.innerText);
  return { tx: terminal.match(/Transacción ([0-9a-f]{64})/)?.[1] ?? null, terminal };
}

const cliente = await open("cliente", 0, 9331);
const programador = await open("programador", 960, 9332);
const summary = {};
try {
  const wc = await walletReady(cliente.page, "cliente");
  const wp = await walletReady(programador.page, "programador");
  if (wc.address === wp.address) throw new Error("Cliente y programador tienen la misma wallet: usa dos cuentas distintas.");
  summary.cliente = wc.address;
  summary.programador = wp.address;
  // Dos tareas de 1 USDC: si el cliente tiene menos de 2 USDC, se fondea desde cyc-client.
  if (wc.units < 20_000_000) {
    const falta = ((20_000_000 - wc.units) / 10_000_000).toFixed(7).replace(/0+$/, "").replace(/[.]$/, "");
    log(`[cliente] fondeando ${falta} USDC desde cyc-client`);
    const out = execFileSync("bash", ["scripts/fondear.sh", wc.address, falta], { cwd: ROOT, encoding: "utf8" });
    summary.fondeo = out.match(/Transacción: ([0-9a-f]{64})/)?.[1];
    log("fondeo", summary.fondeo);
    await wait(cliente.page, () => Number(document.querySelector('[data-testid="saldo-usdc"]')?.getAttribute("data-units")) >= 20_000_000, 60000);
  }

  // ----- Tarea 1: caso A pagado --------------------------------------------------------------
  const t1 = await createAndDeposit(cliente.page);
  await shot(cliente.page, "fase-3-01-cliente-deposito-pollar.png");
  const a = await acceptAndSend(programador.page, t1.invite, "Caso A");
  log("caso A", a.tx);
  await shot(programador.page, "fase-3-02-programador-caso-a-pagado.png");
  summary.tarea1 = { taskId: t1.taskId, deposit: t1.depositTx, release: a.tx };

  // ----- Tarea 2: caso B rechazado y aprobado manualmente --------------------------------------
  const t2 = await createAndDeposit(cliente.page);
  const b = await acceptAndSend(programador.page, t2.invite, "Caso B");
  log("caso B", b.tx ?? "sin pago (rechazado)");
  await shot(programador.page, "fase-3-03-programador-caso-b-rechazado.png");
  await cliente.page.bringToFront();
  await clickText(cliente.page, "button", "Aprobar manualmente", 60000);
  await wait(cliente.page, () => /Aprobación manual confirmado en la red:\s*[0-9a-f]{64}|Aprobación manual: (?!firmando)/.test(document.body.innerText), 180000);
  const text = await cliente.page.evaluate(() => document.body.innerText);
  const manualTx = text.match(/Aprobación manual confirmado en la red:\s*([0-9a-f]{64})/)?.[1] ?? null;
  if (!manualTx) throw new Error("La aprobación manual no se confirmó: " + (text.match(/Aprobación manual: .*/)?.[0] ?? ""));
  log("client_release", manualTx);
  await wait(cliente.page, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Pagada"), 60000);
  await sleep(3500);
  await shot(cliente.page, "fase-3-04-cliente-aprobacion-manual.png");
  summary.tarea2 = { taskId: t2.taskId, deposit: t2.depositTx, client_release: manualTx };
} finally {
  writeFileSync(path.join(ROOT, "scripts", ".logs", "fase3-hito.json"), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary, null, 1));
  await cliente.browser.disconnect(); // las ventanas quedan abiertas
  await programador.browser.disconnect();
}
