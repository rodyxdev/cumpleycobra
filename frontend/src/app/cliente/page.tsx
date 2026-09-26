"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { Money } from "@/components/money";
import { VideoDemo } from "@/components/video-demo";
import { VerdictCard } from "@/components/verdict-card";
import { ClientProposals } from "@/components/client-proposals";
import { RatingCard } from "@/components/rating-card";
import { CopyField } from "@/components/copy-field";
import { AssistedTaskForm } from "@/components/assisted-task-form";
import { StatusCard } from "@/components/status-card";
import { TxResult, type TxState } from "@/components/tx-result";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UsdcGate } from "@/components/usdc-gate";
import { useTask } from "@/hooks/use-task";
import { useWallet } from "@/hooks/use-wallet";
import { api, ApiError, type ClientVerdict } from "@/lib/api";
import { manualApproval } from "@/lib/approval";
import { formatUsdc, shortHash } from "@/lib/format";
import { buildClientRelease, buildDeposit, type UsdcStatus } from "@/lib/soroban";
import { keys, store, useStored, type ClientTask } from "@/lib/store";

export default function ClientePage({ searchParams }: { searchParams: Promise<{ tarea?: string }> }) {
  const { tarea } = use(searchParams);
  const ids = useStored<string[]>(keys.clientTaskIds) ?? [];
  const router = useRouter();

  return (
    <div className="space-y-6">
      <div className="page-heading">
        <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">Vista del cliente</h1>
        <p className="text-base text-muted-foreground">
          Crea la tarea, comparte la invitación con tu programador y deposita el monto en el contrato.
        </p>
      </div>
      {tarea ? (
        <UsdcGate role="cliente">{(usdc) => <ClientTaskPanel taskId={tarea} usdc={usdc} />}</UsdcGate>
      ) : <AssistedTaskForm />}
      {ids.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-medium text-muted-foreground">Tareas creadas en este navegador</div>
            <button type="button" data-testid="limpiar-tareas"
              className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
              onClick={() => {
                const ok = window.confirm(
                  "¿Borrar la lista de tareas de este navegador?\n\nSe borran los enlaces y tokens de esas tareas: ya no podrás ver " +
                  "sus veredictos ni su código desde aquí. Los depósitos y pagos en el contrato no cambian, y tu sesión de Pollar se conserva.",
                );
                if (!ok) return;
                store.clearTasks();
                if (tarea) router.push("/cliente");
              }}>
              Limpiar lista
            </button>
          </div>
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
  const approval = manualApproval({ status, freelancer: task?.freelancer_address, verdicts, secondsLeft });
  const canApprove = approval.can;
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
        <p className="text-sm text-[var(--alert-foreground)]">{error.message}</p>
      ) : null}
      {!sameWallet && (
        <p className="rounded-md border border-[var(--alert)] bg-[var(--alert-background)] p-3 text-sm text-[var(--alert-foreground)]">
          Esta tarea se creó con la wallet {shortHash(ct.client_address, 6)}; conecta esa wallet para depositar o aprobar.
        </p>
      )}

      <section className="space-y-5" aria-label="Veredictos del motor">
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight">Veredictos del motor</h2>
          <p className="max-w-3xl text-base text-muted-foreground">Ves el resultado de cada criterio y el video demo. El código se comparte tras el pago o con autorización explícita del programador.</p>
        </div>
        <div className="flex flex-col-reverse gap-6" data-testid="veredictos">
          {verdicts.length === 0 && <p className="rounded-xl border border-dashed p-6 text-base text-muted-foreground">Todavía no hay envíos.</p>}
          {verdicts.map((v) => (
            <VerdictCard key={v.code_hash} approved={v.approved} reason={v.reason} comparison={v.comparison}
              securityFlags={v.security_flags ?? []} transactionHash={v.transaction_hash} amount={task?.onchain?.amount}
              meta={<>Capa {v.stage === "deterministic" ? "determinista" : v.stage === "cache" ? "caché" : "Gemini"} · código <span className="font-mono">{shortHash(v.code_hash)}</span></>}>
              <VideoDemo url={v.video_url} />
            </VerdictCard>
          ))}
        </div>
      </section>

      <ClientProposals taskId={taskId} clientToken={ct.client_token} clientAddress={ct.client_address}
        freelancerAddress={task?.freelancer_address ?? null} />

      <Card>
        <CardHeader>
          <CardTitle>Tarea {taskId}</CardTitle>
          <CardDescription>
            <Money units={ct.amount} inline /> acordados · plazo de {ct.deadline_minutes} minutos a partir del depósito
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <CopyField label="Enlace de invitación para tu programador" value={invite} secret />
          {!task?.onchain && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">Depósito</div>
              {usdc.units < ct.amount && (
                <p className="text-sm text-[var(--alert-foreground)]">
                  Tu saldo ({formatUsdc(usdc.units)}) no alcanza para el depósito. Para la demo:{" "}
                  <code className="font-mono text-sm">bash scripts/fondear.sh {wallet.address} {formatUsdc(ct.amount - usdc.units).replace(" USDC", "")}</code>
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
            rules_hash <span className="break-all font-mono">{ct.rules_hash}</span>
          </div>
        </CardContent>
      </Card>


      {(canApprove || manual.phase !== "idle") && (
        <Card data-testid="aprobar-manual">
          <CardHeader>
            <CardTitle>Aprobar manualmente</CardTitle>
            <CardDescription>
              {approval.why === "expired"
                ? "Venció el plazo. Puedes pagar al programador de todos modos; si no, cualquiera puede reembolsarte."
                : approval.why === "approved-unpaid"
                  ? "El motor aprobó la entrega, pero el pago automático no se liberó. Puedes pagarle con la aprobación manual."
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

      {status === "Released" && (
        <RatingCard taskId={taskId} clientToken={ct.client_token} clientAddress={task?.onchain?.client ?? ct.client_address} rating={task?.rating} onRated={refresh}
          freelancer={task?.onchain?.freelancer ?? task?.freelancer_address ?? null} />
      )}
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
          <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-5 font-mono text-sm">{code}</pre>
        )}
        {deliveryHash && <p className="break-all text-xs text-muted-foreground">Entrega: {deliveryHash}</p>}
        <VideoDemo url={videoUrl} />
        {error && <p className="text-sm text-[var(--alert-foreground)]">{error}</p>}
      </CardContent>
    </Card>
  );
}
