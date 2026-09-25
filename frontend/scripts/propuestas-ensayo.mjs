// Ensayo aditivo con dos sesiones reales ya iniciadas. Nunca firma retos de identidad.
// Desde frontend: node scripts/propuestas-ensayo.mjs
// Si se interrumpe tras aceptar: --continuar retoma la misma tarea guardada en scripts/.logs.
// Requiere Chrome del ensayo de fase 5 en los puertos 9331/9332, backend :8000 y frontend :3000.
// Crea y deposita una tarea de 20 MXN estimados en testnet; termina con el caso A pagado.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const IMG = path.join(ROOT, "docs/img/propuestas");
const LOGS = path.join(ROOT, "scripts/.logs");
const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const CLIENT = "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL";
const PROGRAMMER = "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ";
mkdirSync(IMG, { recursive: true });
mkdirSync(LOGS, { recursive: true });
const resume = process.argv.includes("--continuar");
const summary = resume ? JSON.parse(readFileSync(path.join(LOGS, "propuestas-ensayo.json"), "utf8"))
  : { started_at: new Date().toISOString(), steps: [] };
if (resume) { summary.previous_error = summary.error; delete summary.error; summary.resumed_at = new Date().toISOString(); }
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const wait = (p, fn, ...args) => p.waitForFunction(fn, { timeout: 90000, polling: 200 }, ...args);
let sessionFailure = null;
const pageErrors = [];

async function tab(port) {
  const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${port}`, defaultViewport: null });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 1100 });
  page.on("pageerror", (e) => pageErrors.push(e.message));
  page.on("response", async (res) => {
    if (new URL(res.url()).origin === API && res.status() === 401) {
      const body = await res.json().catch(() => null);
      if (body?.error === "SESSION_REQUIRED") sessionFailure = "ALTO: verifica de nuevo la identidad";
    }
  });
  return { browser, page };
}
async function session(p, address) {
  if (sessionFailure) throw new Error(sessionFailure);
  await wait(p, () => document.querySelector('header [data-testid="identidad-verificada"], header [data-testid="verificar-identidad"]') || document.body.innerText.includes("Iniciar sesión con Pollar"));
  if (!(await p.$('header [data-testid="identidad-verificada"]'))) throw new Error(`ALTO: inicia sesión con Pollar o verifica la identidad de ${address}`);
  const valid = await p.evaluate(async (address, api) => {
    const s = JSON.parse(localStorage.getItem(`cumpleycobra:sesion:${address}`) ?? "null");
    if (!s || s.address !== address || s.expires_at <= Date.now() / 1000) return false;
    const res = await fetch(`${api}/buzon`, { headers: { Authorization: `Bearer ${s.token}` } });
    return res.ok;
  }, address, API);
  if (!valid) throw new Error(`ALTO: verifica la identidad de ${address}`);
}
async function click(p, selector, label) {
  if (sessionFailure) throw new Error(sessionFailure);
  await wait(p, (s, label) => [...document.querySelectorAll(s)].some((e) => !e.disabled && (!label || e.textContent.trim().startsWith(label))), selector, label);
  await p.evaluate((s, label) => [...document.querySelectorAll(s)].find((e) => !e.disabled && (!label || e.textContent.trim().startsWith(label))).click(), selector, label);
}
async function fill(p, selector, value) {
  await p.bringToFront();
  await p.focus(selector);
  await p.keyboard.down("Control"); await p.keyboard.press("KeyA"); await p.keyboard.up("Control");
  await p.keyboard.press("Backspace"); await p.type(selector, value);
  assert.equal(await p.$eval(selector, (e) => e.value), value);
}
async function shot(p, name, selector) {
  await p.bringToFront();
  await sleep(500);
  if (selector) await (await p.$(selector)).screenshot({ path: path.join(IMG, name) });
  else { await p.evaluate(() => window.scrollTo(0, 0)); await p.screenshot({ path: path.join(IMG, name) }); }
  summary.steps.push({ capture: name, at: new Date().toISOString() });
  console.log(`Captura: ${name}`);
}
const cli = await tab(9331);
const prog = await tab(9332);
const c = cli.page, p = prog.page;
try {
  for (const [page, address] of [[c, CLIENT], [p, PROGRAMMER]]) {
    await page.goto(`${APP}/cliente`, { waitUntil: "load" });
    await session(page, address);
  }
  summary.sessions_valid = true;
  let taskId = summary.task_id;
  let proposal = { id: summary.proposal_id };
  if (!resume) {
    await c.bringToFront();
    await click(c, "button, a", "Usar la plantilla de la demo");
    await wait(c, () => document.querySelector('[data-testid="saldo-usdc"]'));
    assert.equal(await c.$eval('[data-testid="saldo-usdc"]', (e) => e.dataset.address), CLIENT);
    await fill(c, "#monto", "20");
    await fill(c, "#plazo", "10");
    await click(c, "button", "Crear tarea");
    await wait(c, () => location.search.includes("tarea="));
    taskId = new URL(c.url()).searchParams.get("tarea");
    summary.task_id = taskId;
    await session(c, CLIENT);
    await click(c, '[data-testid="depositar"]');
    await wait(c, () => /Depósito confirmado en la red:|Depósito: (?!firmando)/.test(document.body.innerText));
    const depText = await c.evaluate(() => document.body.innerText);
    const deposit = depText.match(/Depósito confirmado en la red:\s*([0-9a-f]{64})/)?.[1];
    if (!deposit) throw new Error("Depósito no confirmado: revisa el mensaje de Pollar en la vista del cliente");
    summary.deposit = deposit;
    await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Depositada"));

    // Perfil del destinatario: el selector usa exclusivamente tareas propias de este navegador.
    await c.goto(`${APP}/programador/${PROGRAMMER}`, { waitUntil: "load" });
    await session(c, CLIENT);
    await click(c, '[data-testid="enviar-propuesta"]');
    await wait(c, (id) => [...document.querySelectorAll("#propuesta-tarea option")].some((o) => o.value === id), taskId);
    await c.select("#propuesta-tarea", taskId);
    await shot(c, "01-perfil-enviar-propuesta.png");
    const createdResponse = c.waitForResponse((res) => new URL(res.url()).pathname === "/propuestas" && res.request().method() === "POST");
    await click(c, '[data-testid="confirmar-propuesta"]');
    const created = await createdResponse;
    assert.equal(created.status(), 200);
    proposal = await created.json();
    assert.equal(proposal.estado, "pendiente");
    summary.proposal_id = proposal.id;
    await wait(c, () => document.querySelector('[data-testid="propuesta-enviada"]'));

    // Buzón: aceptar guarda el mismo freelancer_token usado por la vista de entrega existente.
    await p.bringToFront();
    await p.goto(`${APP}/buzon`, { waitUntil: "load" });
    await session(p, PROGRAMMER);
    await wait(p, (id) => document.querySelector(`[data-proposal-id="${id}"]`), proposal.id);
    await shot(p, "02-buzon.png");
    const acceptedResponse = p.waitForResponse((res) => new URL(res.url()).pathname === `/propuestas/${proposal.id}/aceptar` && res.request().method() === "POST");
    await click(p, `[data-proposal-id="${proposal.id}"] [data-testid="aceptar-propuesta"]`);
    const accepted = await acceptedResponse;
    assert.equal(accepted.status(), 200);
    assert.equal((await accepted.json()).estado, "aceptada");
  } else {
    // Continúa una tarea ya aceptada: no crea otro depósito ni vuelve a aceptar.
    assert.ok(taskId && proposal.id, "Falta una propuesta previa para continuar");
    await p.goto(`${APP}/tarea/${taskId}`, { waitUntil: "load" });
  }
  await wait(p, (id) => location.pathname === `/tarea/${id}` && document.body.innerText.includes("Entregar código"), taskId);
  assert.equal(await p.$eval('[data-testid="saldo-usdc"]', (e) => e.dataset.address), PROGRAMMER);
  summary.accepted = await p.evaluate((id, address) => {
    const stored = JSON.parse(localStorage.getItem(`cumpleycobra:programador:${id}`) ?? "null");
    return stored?.freelancer_address === address && !!stored?.freelancer_token;
  }, taskId, PROGRAMMER);
  assert.equal(summary.accepted, true);
  await shot(p, "03-programador-acepto.png");
  await c.goto(`${APP}/cliente?tarea=${taskId}`, { waitUntil: "load" });
  await wait(c, (id) => document.querySelector(`[data-proposal-id="${id}"]`)?.textContent.includes("Aceptada"), proposal.id);
  await shot(c, "04-propuesta-aceptada.png", '[data-testid="propuestas-cliente"]');
  summary.client_sees_accepted = true;

  await p.bringToFront();
  await session(p, PROGRAMMER);
  await click(p, "button", "Caso A");
  const evaluatedResponse = p.waitForResponse((res) => new URL(res.url()).pathname === "/evaluate" && res.request().method() === "POST", { timeout: 180000 });
  const t0 = Date.now();
  await click(p, '[data-testid="enviar"]');
  const response = await evaluatedResponse;
  assert.equal(response.status(), 200);
  const verdict = await response.json();
  assert.equal(verdict.approved, true);
  assert.match(verdict.transaction_hash ?? "", /^[0-9a-f]{64}$/);
  summary.release = verdict.transaction_hash;
  summary.payment_seconds = (Date.now() - t0) / 1000;
  writeFileSync(path.join(LOGS, "propuestas-evaluate-a.json"), JSON.stringify(verdict, null, 2));
  await wait(p, () => document.querySelector('[aria-label="Veredicto"]')?.textContent.includes("Aprobado y pagado"));
  await shot(p, "05-pago.png", '[aria-label="Veredicto"]');
  await c.reload({ waitUntil: "load" });
  await wait(c, () => document.querySelector('[data-testid="estado"]')?.textContent.includes("Pagada"));
  await shot(c, "06-cliente-pagada.png");
  summary.onchain = (await (await fetch(`${API}/tasks/${taskId}`)).json()).onchain;
  assert.equal(summary.onchain.status, "Released");
  assert.equal(summary.onchain.freelancer, PROGRAMMER);
  const delivered = c.waitForResponse((res) => new URL(res.url()).pathname === `/tasks/${taskId}/delivery` && res.request().method() === "GET" && res.ok());
  await click(c, "button", "Ver código");
  writeFileSync(path.join(LOGS, "propuestas-entrega.py"), (await (await delivered).json()).code);
  assert.deepEqual(pageErrors, []);
  summary.ok = true;
} catch (error) {
  summary.ok = false;
  summary.error = error.message;
  throw error;
} finally {
  summary.page_errors = pageErrors;
  writeFileSync(path.join(LOGS, "propuestas-ensayo.json"), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
  await cli.browser.disconnect(); await prog.browser.disconnect();
}
