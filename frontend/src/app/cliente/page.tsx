"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { ComparisonList } from "@/components/comparison-list";
import { CopyField } from "@/components/copy-field";
import { CriteriaCard } from "@/components/criteria-card";
import { StatusCard } from "@/components/status-card";
import { TxResult, type TxState } from "@/components/tx-result";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UsdcGate } from "@/components/usdc-gate";
import { useTask } from "@/hooks/use-task";
import { useWallet } from "@/hooks/use-wallet";
import { api, ApiError, type ClientVerdict, type Demo } from "@/lib/api";
import { explorerTx, formatUsdc, parseUsdc, shortHash } from "@/lib/format";
import { buildClientRelease, buildDeposit, type UsdcStatus } from "@/lib/soroban";
import { keys, store, useStored, type ClientTask } from "@/lib/store";

export default function ClientePage({ searchParams }: { searchParams: Promise<{ tarea?: string }> }) {
  const { tarea } = use(searchParams);
  const ids = useStored<string[]>(keys.clientTaskIds) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Vista del cliente</h1>
        <p className="text-sm text-muted-foreground">
          Crea la tarea, comparte la invitación con tu programador y deposita el monto en el contrato.
        </p>
      </div>
      <UsdcGate role="cliente">
        {(usdc) => (tarea ? <ClientTaskPanel taskId={tarea} usdc={usdc} /> : <CreateTaskForm />)}
      </UsdcGate>
      {ids.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">Tareas creadas en este navegador</div>
          <div className="flex flex-wrap gap-2">
            {ids.map((id) => (
              <Button key={id} variant={id === tarea ? "secondary" : "outline"} size="sm" nativeButton={false}
                render={<Link href={`/cliente?tarea=${encodeURIComponent(id)}`} />}>
                {id}
              </Button>
            ))}
            {tarea && (
              <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/cliente" />}>
                Nueva tarea
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Crear tarea con la plantilla fija (la dirección es la de la wallet conectada)
// ---------------------------------------------------------------------------
function CreateTaskForm() {
  const router = useRouter();
  const wallet = useWallet();
  const [demo, setDemo] = useState<Demo | null>(null);
  const [amount, setAmount] = useState("1");
  const [minutes, setMinutes] = useState("10");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    api.demo().then(setDemo, (e: ApiError) => setError(e.message));
  }, []);

  const units = parseUsdc(amount);
  const mins = /^\d+$/.test(minutes) ? Number(minutes) : NaN;
  const valid = demo && wallet.address && units !== null && mins > 0;

  async function create() {
    if (!demo || units === null || !wallet.address) return;
    setSending(true);
    setError(null);
    try {
      const created = await api.createTask({
        client_address: wallet.address,
        raw_request: demo.raw_request,
        ...demo.spec,
        amount: units,
        deadline_minutes: mins,
      });
      store.saveClientTask({ ...created, amount: units, deadline_minutes: mins, client_address: wallet.address });
      router.replace(`/cliente?tarea=${encodeURIComponent(created.task_id)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setSending(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      {demo ? (
        <CriteriaCard spec={demo.spec} title="Plantilla: aplicar_descuento" />
      ) : (
        <Card>
          <CardContent className="text-sm text-muted-foreground">Cargando la plantilla…</CardContent>
        </Card>
      )}
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>Nueva tarea</CardTitle>
          <CardDescription>Los criterios de la plantilla quedan fijos y se firman con su hash.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="monto">Monto (USDC)</Label>
              <Input id="monto" value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="plazo">Plazo (minutos)</Label>
              <Input id="plazo" value={minutes} inputMode="numeric" onChange={(e) => setMinutes(e.target.value)} />
            </div>
          </div>
          {units !== null && <p className="text-xs text-muted-foreground">{units.toLocaleString("es-MX")} unidades del token</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button className="w-full" disabled={!valid || sending} onClick={create}>
            {sending ? "Creando…" : "Crear tarea"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel de una tarea creada
// ---------------------------------------------------------------------------
function ClientTaskPanel({ taskId, usdc }: { taskId: string; usdc: UsdcStatus }) {
  const wallet = useWallet();
  const ct = useStored<ClientTask>(keys.clientTask(taskId));
  const { task, error, secondsLeft, refresh } = useTask(taskId);
  const verdicts = useVerdicts(taskId, ct?.client_token ?? null);
  const [deposit, setDeposit] = useState<TxState>({ phase: "idle" });
  const [manual, setManual] = useState<TxState>({ phase: "idle" });

  if (!ct) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">
          La tarea {taskId} no se creó en este navegador: sus tokens no están aquí.
        </CardContent>
      </Card>
    );
  }

  const sameWallet = wallet.address === ct.client_address;
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const invite = `${origin}/tarea/${encodeURIComponent(taskId)}?invitacion=${encodeURIComponent(ct.invite_token)}`;
  const depositCmd = `bash scripts/deposit.sh ${taskId} ${ct.amount} ${ct.deadline_minutes * 60} ${ct.rules_hash}`;
  const status = task?.onchain?.status;
  const rejected = verdicts.some((v) => !v.approved);
  const expired = status === "Funded" && secondsLeft !== null && secondsLeft <= 0;
  const canApprove = status === "Funded" && !!task?.freelancer_address && (rejected || expired);
  const walletLabel = wallet.mode === "pollar" ? "Pollar" : "Freighter";

  async function run(set: (s: TxState) => void, build: () => Promise<string>) {
    set({ phase: "signing" });
    try {
      const hash = await wallet.signAndSend(await build());
      set({ phase: "done", hash });
      refresh();
    } catch (e) {
      set({ phase: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div className="space-y-6">
      {task ? <StatusCard task={task} secondsLeft={secondsLeft} /> : error ? (
        <p className="text-sm text-red-600">{error.message}</p>
      ) : null}
      {!sameWallet && (
        <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Esta tarea se creó con la wallet {shortHash(ct.client_address, 6)}; conecta esa wallet para depositar o aprobar.
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Tarea {taskId}</CardTitle>
          <CardDescription>
            {formatUsdc(ct.amount)} acordados · plazo de {ct.deadline_minutes} minutos a partir del depósito
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <CopyField label="Enlace de invitación para tu programador" value={invite} secret />
          {!task?.onchain && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">Depósito</div>
              {usdc.units < ct.amount && (
                <p className="text-sm text-amber-700">
                  Tu saldo ({formatUsdc(usdc.units)}) no alcanza para el depósito. Para la demo:{" "}
                  <code className="font-mono text-xs">bash scripts/fondear.sh {wallet.address} {formatUsdc(ct.amount - usdc.units).replace(" USDC", "")}</code>
                </p>
              )}
              <Button
                data-testid="depositar"
                disabled={!sameWallet || deposit.phase === "signing" || usdc.units < ct.amount}
                onClick={() =>
                  run(setDeposit, () =>
                    buildDeposit({
                      client: ct.client_address,
                      taskId,
                      amount: ct.amount,
                      deadlineSecs: ct.deadline_minutes * 60,
                      rulesHash: ct.rules_hash,
                    }),
                  )
                }
              >
                {deposit.phase === "signing" ? "Firmando y enviando…" : `Depositar ${formatUsdc(ct.amount)} con ${walletLabel}`}
              </Button>
            </div>
          )}
          <TxResult state={deposit} label="Depósito" />
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Plan C: depositar con la Stellar CLI</summary>
            <div className="mt-2">
              <CopyField label="Comando" value={depositCmd} />
            </div>
          </details>
          <div className="text-xs text-muted-foreground">
            rules_hash <span className="font-mono">{ct.rules_hash}</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Veredictos del motor</CardTitle>
          <CardDescription>
            Ves el motivo y el resultado de cada criterio. El código solo se entrega cuando el programador cobra.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5" data-testid="veredictos">
          {verdicts.length === 0 && <p className="text-sm text-muted-foreground">Todavía no hay envíos.</p>}
          {verdicts.map((v) => (
            <div key={v.code_hash} className="space-y-2 border-l-2 pl-4" style={{ borderColor: v.approved ? "#059669" : "#dc2626" }}>
              <div className="flex items-center gap-2">
                <Badge variant={v.approved ? "default" : "destructive"}>{v.approved ? "Aprobado" : "Rechazado"}</Badge>
                <span className="text-xs text-muted-foreground">
                  capa {v.stage === "deterministic" ? "determinista" : "Gemini"} · código {shortHash(v.code_hash)}
                </span>
              </div>
              <p className="text-sm">{v.reason}</p>
              <ComparisonList items={v.comparison} />
              {v.transaction_hash && (
                <a className="text-sm text-sky-700 underline" href={explorerTx(v.transaction_hash)} target="_blank" rel="noreferrer">
                  Pago en el explorador: {shortHash(v.transaction_hash)}
                </a>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      {(canApprove || manual.phase !== "idle") && (
        <Card data-testid="aprobar-manual">
          <CardHeader>
            <CardTitle>Aprobar manualmente</CardTitle>
            <CardDescription>
              {expired
                ? "Venció el plazo. Puedes pagar al programador de todos modos; si no, cualquiera puede reembolsarte."
                : "El motor rechazó la entrega. Si aun así la aceptas, el contrato le paga al programador."}{" "}
              El pago va a {task?.freelancer_address ? shortHash(task.freelancer_address, 6) : "la wallet del programador"}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {canApprove && (
              <Button
                variant="outline"
                disabled={!sameWallet || manual.phase === "signing"}
                onClick={() =>
                  run(setManual, () =>
                    buildClientRelease({ client: ct.client_address, taskId, freelancer: task!.freelancer_address! }),
                  )
                }
              >
                {manual.phase === "signing" ? "Firmando y enviando…" : `Aprobar manualmente con ${walletLabel}`}
              </Button>
            )}
            <TxResult state={manual} label="Aprobación manual" />
          </CardContent>
        </Card>
      )}

      {status === "Released" && <Delivery taskId={taskId} clientToken={ct.client_token} />}
    </div>
  );
}

function useVerdicts(taskId: string, clientToken: string | null): ClientVerdict[] {
  const [verdicts, setVerdicts] = useState<ClientVerdict[]>([]);
  useEffect(() => {
    if (!clientToken) return;
    let alive = true;
    const load = () =>
      api.verdicts(taskId, clientToken).then(
        (r) => alive && setVerdicts(r.verdicts),
        () => undefined,
      );
    const first = setTimeout(load, 0);
    const id = setInterval(load, 3000);
    return () => {
      alive = false;
      clearTimeout(first);
      clearInterval(id);
    };
  }, [taskId, clientToken]);
  return verdicts;
}

function Delivery({ taskId, clientToken }: { taskId: string; clientToken: string }) {
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Código entregado</CardTitle>
        <CardDescription>El programador ya cobró: el código es tuyo.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {code === null ? (
          <Button variant="outline" onClick={() => api.delivery(taskId, clientToken).then((d) => setCode(d.code), (e: ApiError) => setError(e.message))}>
            Ver código
          </Button>
        ) : (
          <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">{code}</pre>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </CardContent>
    </Card>
  );
}
