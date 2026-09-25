"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { Money } from "@/components/money";
import { VideoDemo } from "@/components/video-demo";
import { ComparisonList } from "@/components/comparison-list";
import { CopyField } from "@/components/copy-field";
import { AssistedTaskForm } from "@/components/assisted-task-form";
import { StatusCard } from "@/components/status-card";
import { TxResult, type TxState } from "@/components/tx-result";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UsdcGate } from "@/components/usdc-gate";
import { useTask } from "@/hooks/use-task";
import { useWallet } from "@/hooks/use-wallet";
import { api, ApiError, type ClientVerdict } from "@/lib/api";
import { explorerTx, formatUsdc, shortHash } from "@/lib/format";
import { buildClientRelease, buildDeposit, type UsdcStatus } from "@/lib/soroban";
import { keys, useStored, type ClientTask } from "@/lib/store";

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
      {tarea ? (
        <UsdcGate role="cliente">{(usdc) => <ClientTaskPanel taskId={tarea} usdc={usdc} />}</UsdcGate>
      ) : <AssistedTaskForm />}
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
            <Money units={ct.amount} /> acordados · plazo de {ct.deadline_minutes} minutos a partir del depósito
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
            <summary className="cursor-pointer">Respaldo si la wallet no firma el depósito</summary>
            <p className="mt-2">
              Un depósito desde la terminal lo firma otra cuenta, y el motor exige que el cliente en el contrato sea
              quien creó la tarea. Crea una tarea nueva desde la terminal con{" "}
              <code className="font-mono">backend/.venv/Scripts/python scripts/tarea_respaldo.py</code> y comparte el
              enlace que imprime.
            </p>
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
            Ves el resultado de cada criterio y el video demo. El código se comparte tras el pago o con autorización explícita del programador.
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
              <VideoDemo url={v.video_url} />
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

      {(status === "Released" || verdicts.some((v) => v.consented)) && <Delivery taskId={taskId} clientToken={ct.client_token} paid={status === "Released"} />}
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

function Delivery({ taskId, clientToken, paid }: { taskId: string; clientToken: string; paid: boolean }) {
  const [deliveryHash, setDeliveryHash] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{paid ? "Código entregado" : "Código compartido con consentimiento"}</CardTitle>
        <CardDescription>{paid ? "El programador ya cobró: el código es tuyo." : "El programador autorizó revisar una entrega rechazada. El pago todavía depende de tu aprobación manual."}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {code === null ? (
          <Button variant="outline" onClick={() => api.delivery(taskId, clientToken).then((d) => { setCode(d.code); setDeliveryHash(d.code_hash); setVideoUrl(d.video_url); }, (e: ApiError) => setError(e.message))}>
            Ver código
          </Button>
        ) : (
          <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">{code}</pre>
        )}
        {deliveryHash && <p className="break-all text-xs text-muted-foreground">Entrega: {deliveryHash}</p>}
        <VideoDemo url={videoUrl} />
        {error && <p className="text-sm text-red-600">{error}</p>}
      </CardContent>
    </Card>
  );
}
