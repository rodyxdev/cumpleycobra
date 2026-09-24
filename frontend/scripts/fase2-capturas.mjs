// Recorre el flujo de la fase 2 en un Chrome real (headless) y guarda capturas.
//
//   Tarea 1: cliente crea la tarea -> depósito con scripts/deposit.sh -> programador acepta
//            -> un clic en "Enviar" con el caso A -> hash del release en pantalla.
//   Tarea 2: igual, pero con el caso C -> rechazo por seguridad; vista del cliente del rechazo.
//
// Requisitos: backend en :8000, frontend en :3000, Chrome instalado, identidades cyc-* de la
// Stellar CLI y 2 USDC en cyc-client. Uso (desde frontend/): node scripts/fase2-capturas.mjs

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const IMG = path.join(ROOT, "docs", "fases", "img");
const APP = "http://localhost:3000";
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
mkdirSync(IMG, { recursive: true });

const pub = (id) => execFileSync("stellar", ["keys", "public-key", id], { encoding: "utf8" }).trim();
const CLIENT = pub("cyc-client");
const FREELANCER = pub("cyc-freelancer");
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

async function clickText(page, selector, text) {
  await page.waitForFunction(
    (s, t) => [...document.querySelectorAll(s)].some((e) => e.textContent.trim().startsWith(t) && !e.disabled),
    { polling: 250, timeout: 30000 }, selector, text,
  );
  await page.evaluate((s, t) => {
    [...document.querySelectorAll(s)].find((e) => e.textContent.trim().startsWith(t) && !e.disabled).click();
  }, selector, text);
}

const codeStartingWith = (page, prefix) =>
  page.waitForFunction(
    (p) => [...document.querySelectorAll("code")].map((c) => c.textContent).find((t) => t.includes(p)),
    { polling: 250, timeout: 30000 }, prefix,
  ).then((h) => h.jsonValue());

async function shot(page, name) {
  const file = path.join(IMG, name);
  await page.screenshot({ path: file, fullPage: true });
  log("captura", path.relative(ROOT, file));
}

async function createAndFund(page) {
  await page.bringToFront(); // una pestaña en segundo plano no se dibuja y el clic no avanza
  await page.goto(`${APP}/cliente`, { waitUntil: "load" });
  await page.waitForFunction(() => document.body.innerText.includes("Plantilla: aplicar_descuento"), { polling: 250, timeout: 30000 });
  await page.click("#cliente", { count: 3 });
  await page.type("#cliente", CLIENT);
  await clickText(page, "button", "Crear tarea");
  await page.waitForFunction(() => location.search.includes("tarea="), { polling: 250, timeout: 30000 });
  const taskId = new URL(page.url()).searchParams.get("tarea");
  const cmd = await codeStartingWith(page, "bash scripts/deposit.sh");
  const invite = await codeStartingWith(page, "/tarea/");
  log("tarea", taskId);
  const args = cmd.split(" ").slice(1); // ["scripts/deposit.sh", id, monto, segundos, rules_hash]
  const out = execFileSync("bash", args, { cwd: ROOT, encoding: "utf8" });
  const depositTx = out.match(/Transacción: ([0-9a-f]{64})/)?.[1];
  log("deposit", depositTx);
  await page.waitForFunction(
    () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Depositada"),
    { polling: 250, timeout: 60000 },
  );
  return { taskId, invite, depositTx };
}

async function acceptAndSend(page, invite, caseLabel) {
  await page.bringToFront();
  await page.goto(invite, { waitUntil: "load" });
  await page.waitForSelector("#programador");
  await page.click("#programador", { count: 3 });
  await page.type("#programador", FREELANCER);
  await clickText(page, "button", "Acepto los criterios");
  await page.waitForFunction(() => document.body.innerText.includes("Entregar código"), { polling: 250, timeout: 30000 });
  await clickText(page, "button", caseLabel);
  await page.waitForFunction(
    () => document.querySelector('[data-testid="plazo"]')?.textContent.match(/\d\d:\d\d/),
    { polling: 250, timeout: 30000 },
  );
  const started = Date.now();
  await clickText(page, '[data-testid="enviar"]', "Enviar"); // el clic del hito
  // Muestras de la terminal cada 300 ms hasta que termina: evidencia del contador real.
  const samples = [];
  let waiting = null;
  const done = /Sin pago|Transacción [0-9a-f]{64}|Error /;
  for (let i = 0; i < 400; i++) {
    const text = await page.evaluate(() => document.querySelector('[data-testid="terminal"]')?.textContent ?? "(sin terminal) " + document.body.innerText.slice(0, 200));
    const t = ((Date.now() - started) / 1000).toFixed(1);
    if (i < 8 || i % 10 === 0) samples.push(`${t} s: ${text.slice(0, 120)}`);
    if (!waiting && text.includes("Enviando al motor")) waiting = `${t} s: ${text}`;
    if (done.test(text)) break;
    await new Promise((r) => setTimeout(r, 300));
  }
  log("muestras", "\n  " + samples.join("\n  "));
  await new Promise((r) => setTimeout(r, 800));
  const terminal = await page.$eval('[data-testid="terminal"]', (e) => e.innerText);
  const tx = terminal.match(/Transacción ([0-9a-f]{64})/)?.[1] ?? null;
  return { tx, terminal, waiting, seconds: (Date.now() - started) / 1000 };
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  defaultViewport: { width: 1280, height: 900 },
  args: ["--lang=es-MX"],
  protocolTimeout: 150000,
});
const summary = {};
try {
  const client = await browser.newPage();
  const dev = await browser.newPage();
  for (const [name, pg] of [["cliente", client], ["programador", dev]]) {
    pg.on("pageerror", (e) => log(`[${name}] error en la página:`, e.message));
    pg.on("console", (m) => m.type() === "error" && log(`[${name}] consola:`, m.text()));
  }

  // ----- Tarea 1: caso A -------------------------------------------------------------
  const t1 = await createAndFund(client);
  await shot(client, "fase-2-01-cliente-tarea-creada.png");
  const a = await acceptAndSend(dev, t1.invite, "Caso A");
  log("caso A", a.tx, `${a.seconds.toFixed(1)} s`);
  await shot(dev, "fase-2-02-programador-caso-a-pagado.png");
  await client.bringToFront();
  await client.waitForFunction(
    () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Pagada"),
    { polling: 250, timeout: 30000 },
  );
  await new Promise((r) => setTimeout(r, 3500)); // un ciclo de consulta de veredictos
  await shot(client, "fase-2-03-cliente-tarea-pagada.png");
  summary.tarea1 = { ...t1, release: a.tx, segundos: a.seconds, espera: a.waiting, terminal: a.terminal };

  // ----- Tarea 2: caso C -------------------------------------------------------------
  const t2 = await createAndFund(client);
  const c = await acceptAndSend(dev, t2.invite, "Caso C");
  log("caso C", c.tx ?? "sin pago", `${c.seconds.toFixed(1)} s`);
  await shot(dev, "fase-2-04-programador-caso-c-rechazado.png");
  await client.bringToFront();
  await client.waitForFunction(
    () => document.querySelector('[data-testid="veredictos"]')?.innerText.includes("Rechazado"),
    { polling: 250, timeout: 30000 },
  );
  await shot(client, "fase-2-05-cliente-caso-c-rechazado.png");
  const clientText = await client.$eval("main", (e) => e.innerText);
  summary.tarea2 = {
    ...t2,
    release: c.tx,
    segundos: c.seconds,
    terminal: c.terminal,
    // La vista del cliente no debe mostrar trace, logic ni el código.
    cliente_muestra_codigo: clientText.includes("def aplicar_descuento"),
    cliente_muestra_trace: c.terminal
      .split("\n")
      .filter((l) => l && !/^[✓✗]/.test(l.trim()) && l.length > 40 && !l.startsWith("$") && !l.startsWith("Respuesta"))
      .slice(0, 3)
      .some((l) => clientText.includes(l)),
  };
} finally {
  await browser.close();
  writeFileSync(path.join(ROOT, "scripts", ".logs", "fase2-capturas.json"), JSON.stringify(summary, null, 1));
}
console.log(JSON.stringify(summary, null, 1));
