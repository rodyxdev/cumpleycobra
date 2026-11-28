"use client";

import { useState } from "react";
import * as freighter from "@stellar/freighter-api";
import { AlertTriangle, ExternalLink, Wallet } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { canonicalJson, objetoAcordado, sha256Hex } from "@/lib/acuerdo";
import {
  buildCall,
  CALLS,
  contractUrl,
  formatUsdc,
  MAINNET,
  MainnetError,
  parseUsdc,
  readTask,
  submitAndWait,
  txUrl,
  type MainnetFn,
  type MainnetTask,
} from "@/lib/mainnet";

// Acuerdo fijo de las tareas de prueba: su rules_hash se calcula aquí con la misma
// definición del backend (ver /verificar) y queda guardado on-chain al depositar.
const ACUERDO = {
  task_id: "",
  description: "Tarea de prueba de Cumple&Cobra en mainnet (Ship It, edición experimental).",
  criteria: ["La tarea existe solo para probar el contrato en la red principal con montos mínimos."],
  language: "python",
  allowed_deps: [] as string[],
  examples: [] as { input: string; output: string }[],
};

type Registro = { fn: MainnetFn; hash: string; at: string };

/** Edición experimental en mainnet: el cliente firma con Freighter las cinco funciones. */
export default function MainnetPage() {
  const [address, setAddress] = useState<string | null>(null);
  const [taskId, setTaskId] = useState("");
  const [amount, setAmount] = useState("0.5");
  const [minutes, setMinutes] = useState("10");
  const [topUp, setTopUp] = useState("0.2");
  const [extraMin, setExtraMin] = useState("5");
  const [freelancer, setFreelancer] = useState("");
  const [task, setTask] = useState<MainnetTask | null>(null);
  const [readAt, setReadAt] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<Registro[]>([]);
  const deployed = Boolean(MAINNET.contractId);

  async function connect() {
    setError(null);
    try {
      const conn = await freighter.isConnected();
      if (!conn.isConnected) throw new MainnetError("No se encontró la extensión Freighter en este navegador.");
      const access = await freighter.requestAccess();
      if (access.error) throw new MainnetError(`Freighter no dio acceso: ${access.error.message ?? access.error}`);
      const net = await freighter.getNetworkDetails();
      if (net.networkPassphrase !== MAINNET.passphrase)
        throw new MainnetError("Freighter no está en Mainnet: cámbialo a «Mainnet» en la extensión y vuelve a conectar.");
      setAddress(access.address);
      setFreelancer((f) => f || access.address);
      // Identificador nuevo para cada sesión (se puede cambiar para leer una tarea anterior).
      setTaskId((t) => t || `mn-${Date.now().toString(36)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function refresh(id = taskId, who = address) {
    if (!who) return;
    try {
      setTask(await readTask(who, id));
      setReadAt(Math.floor(Date.now() / 1000));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function run(fn: MainnetFn, args: () => Promise<Parameters<typeof buildCall>[2]> | Parameters<typeof buildCall>[2]) {
    if (!address) return;
    setBusy(fn);
    setError(null);
    try {
      const xdr = await buildCall(address, fn, await args());
      const signed = await freighter.signTransaction(xdr, { networkPassphrase: MAINNET.passphrase, address });
      if (signed.error) throw new MainnetError(`Freighter no firmó: ${signed.error.message ?? signed.error}`);
      const hash = await submitAndWait(signed.signedTxXdr);
      setLog((l) => [{ fn, hash, at: new Date().toLocaleTimeString("es-MX") }, ...l]);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const minutesToSecs = (m: string) => {
    if (!/^\d+$/.test(m.trim()) || Number(m) <= 0) throw new MainnetError("Los minutos deben ser un entero mayor que cero.");
    return BigInt(m.trim()) * BigInt(60);
  };

  // Segundos que faltaban al leer la tarea (se actualiza con «Leer tarea»).
  const secondsLeft = task ? task.deadline - readAt : null;
  const disabled = !address || !deployed || !taskId.trim() || busy !== null;

  return (
    <div className="space-y-8">
      <div className="page-heading">
        <span className="justify-self-start rounded-full bg-secondary px-3 py-1 text-xs font-bold tracking-[0.06em] text-primary uppercase">Mainnet · experimental</span>
        <h1>El contrato en la red principal de Stellar</h1>
        <p className="max-w-2xl text-base text-muted-foreground">
          Edición experimental para la misión especial de Ship It: el mismo contrato de Cumple&amp;Cobra, desplegado en mainnet,
          que usas aquí con tu propia wallet y {MAINNET.token.symbol} real.
        </p>
      </div>

      <div className="alert-panel flex gap-3 text-sm">
        <AlertTriangle className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div className="space-y-1">
          <p className="font-semibold">Dinero real, contrato sin auditoría.</p>
          <p>Usa solo montos mínimos de {MAINNET.token.symbol} y tu propia wallet. Esta página no usa el backend ni la llave del árbitro: todo lo firmas tú en Freighter. El flujo normal de Cumple&amp;Cobra sigue en testnet.</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Wallet y contrato</CardTitle>
          <CardDescription>
            {deployed ? (
              <a className="inline-flex items-center gap-1 underline" href={contractUrl()} target="_blank" rel="noreferrer">
                Contrato {MAINNET.contractId.slice(0, 8)}…{MAINNET.contractId.slice(-5)} en stellar.expert <ExternalLink className="size-3.5" />
              </a>
            ) : "El contrato de mainnet todavía no está desplegado: los botones se activan al desplegarlo."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {address ? (
            <p className="text-sm">Conectado: <span className="font-mono break-all">{address}</span></p>
          ) : (
            <Button className="min-h-10" onClick={connect}><Wallet /> Conectar Freighter (Mainnet)</Button>
          )}
          <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
            <div className="space-y-2">
              <Label htmlFor="task">Identificador de la tarea</Label>
              <Input id="task" value={taskId} onChange={(e) => setTaskId(e.target.value)} placeholder="Se genera al conectar" autoComplete="off" />
            </div>
            <Button variant="outline" className="min-h-10" disabled={!address || !deployed} onClick={() => refresh()}>Leer tarea</Button>
          </div>
          {task && (
            <p className="text-sm text-muted-foreground">
              Estado: <b>{task.status}</b> · Monto: <b>{formatUsdc(task.amount)} {MAINNET.token.symbol}</b> ·{" "}
              {secondsLeft !== null && secondsLeft > 0 ? `vence en ${Math.ceil(secondsLeft / 60)} min` : "plazo vencido"}
            </p>
          )}
          {error && <p className="text-sm text-danger">{error}</p>}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>1. <code>deposit</code></CardTitle>
            <CardDescription>Depositas {MAINNET.token.symbol} en el contrato con el rules_hash del acuerdo de prueba.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="amount">Monto ({MAINNET.token.symbol})</Label><Input id="amount" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
            <div className="space-y-2"><Label htmlFor="minutes">Plazo (minutos)</Label><Input id="minutes" value={minutes} onChange={(e) => setMinutes(e.target.value)} /></div>
            <Button className="min-h-10 sm:col-span-2" disabled={disabled} onClick={() => run("deposit", async () => {
              const rulesHash = await sha256Hex(canonicalJson(objetoAcordado({ ...ACUERDO, task_id: taskId })));
              return CALLS.deposit({ client: address!, taskId, amount: parseUsdc(amount), deadlineSecs: minutesToSecs(minutes), rulesHash });
            })}>{busy === "deposit" ? "Firmando…" : "Depositar"}</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>2. <code>top_up_task</code></CardTitle>
            <CardDescription>Agregas {MAINNET.token.symbol} a la tarea depositada, antes del plazo.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2"><Label htmlFor="topup">Monto extra ({MAINNET.token.symbol})</Label><Input id="topup" value={topUp} onChange={(e) => setTopUp(e.target.value)} /></div>
            <Button className="min-h-10 w-full" disabled={disabled} onClick={() => run("top_up_task", () => CALLS.top_up_task({ taskId, amount: parseUsdc(topUp) }))}>
              {busy === "top_up_task" ? "Firmando…" : "Recargar"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>3. <code>extend_deadline</code></CardTitle>
            <CardDescription>Le das más tiempo al programador; el plazo solo crece.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2"><Label htmlFor="extra">Minutos extra</Label><Input id="extra" value={extraMin} onChange={(e) => setExtraMin(e.target.value)} /></div>
            <Button className="min-h-10 w-full" disabled={disabled} onClick={() => run("extend_deadline", () => CALLS.extend_deadline({ taskId, extraSecs: minutesToSecs(extraMin) }))}>
              {busy === "extend_deadline" ? "Firmando…" : "Prorrogar"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>4. <code>client_release</code></CardTitle>
            <CardDescription>Apruebas manualmente y el contrato paga al programador.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2"><Label htmlFor="freelancer">Dirección del programador</Label><Input id="freelancer" value={freelancer} onChange={(e) => setFreelancer(e.target.value)} placeholder="G…" /></div>
            <Button className="min-h-10 w-full" disabled={disabled || !freelancer} onClick={() => run("client_release", () => CALLS.client_release({ taskId, freelancer: freelancer.trim() }))}>
              {busy === "client_release" ? "Firmando…" : "Pagar"}
            </Button>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>5. <code>timeout_refund</code></CardTitle>
            <CardDescription>Cuando vence el plazo sin pago, cualquiera lo dispara y el depósito vuelve íntegro al cliente.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button className="min-h-10" disabled={disabled} onClick={() => run("timeout_refund", () => CALLS.timeout_refund({ taskId }))}>
              {busy === "timeout_refund" ? "Firmando…" : "Reembolsar por plazo"}
            </Button>
          </CardContent>
        </Card>
      </div>

      {log.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Transacciones de esta sesión</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm">
              {log.map((r) => (
                <li key={r.hash} className="flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground">{r.at}</span>
                  <code>{r.fn}</code>
                  <a className="inline-flex items-center gap-1 font-mono underline" href={txUrl(r.hash)} target="_blank" rel="noreferrer">
                    {r.hash.slice(0, 10)}… <ExternalLink className="size-3.5" />
                  </a>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
