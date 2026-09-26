"use client";

import { use, useEffect, useState } from "react";

import { SubmissionResult } from "@/components/submission-result";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CriteriaCard } from "@/components/criteria-card";
import { StatusCard } from "@/components/status-card";
import { useTerminal } from "@/components/terminal";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { UsdcGate } from "@/components/usdc-gate";
import { UsdcTrustlineNotice } from "@/components/usdc-trustline-notice";
import { useTask } from "@/hooks/use-task";
import { useWallet } from "@/hooks/use-wallet";
import { api, ApiError, type Caso, type TaskView, type Verdict } from "@/lib/api";
import { keys, store, useStored, type FreelancerTask } from "@/lib/store";

const MIN_SECONDS = 120; // mismo margen que el backend (DEADLINE_TOO_CLOSE)

export default function TareaPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ invitacion?: string }>;
}) {
  const { id } = use(params);
  const { invitacion } = use(searchParams);
  const { task, error, secondsLeft, refresh } = useTask(id);
  const mine = useStored<FreelancerTask>(keys.freelancerTask(id));
  const wallet = useWallet();

  if (!task) {
    return <p className="text-sm text-muted-foreground">{error ? error.message : "Cargando la tarea…"}</p>;
  }

  // Aceptada por esta wallet: el token guardado es de la dirección amarrada y de la wallet conectada.
  const accepted =
    mine && task.freelancer_address === mine.freelancer_address && wallet.address === mine.freelancer_address;
  const takenByOther = task.freelancer_address && task.freelancer_address !== wallet.address;

  return (
    <div className="space-y-6">
      <div className="page-heading">
        <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">Vista del programador</h1>
        <p className="text-base text-muted-foreground">
          Tarea {id}. Estos son los criterios que el motor va a verificar; el monto es el que está en el contrato.
        </p>
      </div>
      <StatusCard task={task} secondsLeft={secondsLeft} />
      <UsdcGate role="programador">
        {() => (
          <div className="grid gap-6">
            <div className="order-2 min-w-0"><CriteriaCard spec={task} /></div>
            {accepted ? (
              <SubmitPanel task={task} mine={mine} secondsLeft={secondsLeft} onDone={refresh} />
            ) : takenByOther ? (
              <Card className="order-3">
                <CardContent className="text-sm text-muted-foreground">
                  Esta tarea ya la aceptó otra wallet. Solo esa wallet puede entregar y cobrar.
                </CardContent>
              </Card>
            ) : (
              <div className="order-3"><AcceptPanel taskId={id} invite={invitacion ?? null} onAccepted={refresh} /></div>
            )}
          </div>
        )}
      </UsdcGate>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aceptar criterios
// ---------------------------------------------------------------------------
function AcceptPanel({ taskId, invite, onAccepted }: { taskId: string; invite: string | null; onAccepted: () => void }) {
  const wallet = useWallet();
  const [error, setError] = useState<ApiError | null>(null);
  const [sending, setSending] = useState(false);
  const addr = wallet.address ?? "";

  async function accept() {
    if (!invite || !addr) return;
    setSending(true);
    setError(null);
    try {
      const { freelancer_token } = await api.accept(taskId, addr, invite);
      store.saveFreelancerTask({ task_id: taskId, freelancer_token, freelancer_address: addr });
      onAccepted();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "ERROR", String(e)));
    } finally {
      setSending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Aceptar los criterios</CardTitle>
        <CardDescription>
          Al aceptar, la tarea queda amarrada a la dirección de tu wallet ({addr.slice(0, 6)}…{addr.slice(-4)}): el
          pago solo puede ir a ella.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!invite && (
          <p className="text-sm text-[var(--alert-foreground)]">Necesitas el enlace de invitación que te compartió el cliente.</p>
        )}
        {error?.code === "NO_USDC_TRUSTLINE" ? (
          <UsdcTrustlineNotice />
        ) : error ? (
          <p className="text-sm text-[var(--alert-foreground)]">{error.message}</p>
        ) : null}
        <Button disabled={!invite || !addr || sending} onClick={accept} data-testid="aceptar">
          {sending ? "Aceptando…" : "Acepto los criterios"}
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Elegir caso, enviar y ver la terminal
// ---------------------------------------------------------------------------
function SubmitPanel({
  task,
  mine,
  secondsLeft,
  onDone,
}: {
  task: TaskView;
  mine: FreelancerTask;
  secondsLeft: number | null;
  onDone: () => void;
}) {
  const [casos, setCasos] = useState<Caso[]>([]);
  const [selected, setSelected] = useState<string>("A");
  const [video, setVideo] = useState("");
  const [consentError, setConsentError] = useState<string | null>(null);
  const [consenting, setConsenting] = useState(false);
  const [checked, setChecked] = useState(false);
  const [consentFor, setConsentFor] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [pasted, setPasted] = useState("");
  // El veredicto que devolvió /evaluate: la tarjeta lo muestra tal cual, sin leer la terminal.
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const { lines, busy, now, run } = useTerminal();

  useEffect(() => {
    api.demo().then((d) => setCasos(d.casos), () => undefined);
  }, []);

  const caso = casos.find((c) => c.id === selected);
  const code = selected === "pegar" ? pasted : caso?.codigo ?? "";
  const label = selected === "pegar" ? "código pegado" : caso?.nombre ?? selected;

  const funded = task.onchain?.status === "Funded";
  const enoughTime = secondsLeft !== null && secondsLeft >= MIN_SECONDS;
  const blocked = !funded
    ? task.onchain
      ? "La tarea ya no está depositada."
      : "El cliente todavía no deposita el monto."
    : !enoughTime
      ? `Quedan menos de ${MIN_SECONDS} s de plazo: ya no se puede enviar.`
      : null;

  async function send() {
    setVerdict(null);
    setVerdict(await run(label, () => api.evaluate(task.task_id, mine.freelancer_address, code, mine.freelancer_token, video.trim() || null)));
    onDone();
  }

  const principales = casos.filter((c) => c.principal);
  const extra = casos.filter((c) => !c.principal);

  return (
    <div className="contents">
      <SubmissionResult lines={lines} now={now} busy={busy} amount={task.onchain?.amount} verdict={verdict} />
      <Card className="order-3 min-w-0">
        <CardHeader>
          <CardTitle>Entregar código</CardTitle>
          <CardDescription>Aceptaste los criterios con {mine.freelancer_address.slice(0, 8)}…</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {principales.map((c) => (
              <Button key={c.id} variant={selected === c.id ? "default" : "outline"} size="sm" onClick={() => setSelected(c.id)}>
                {c.nombre}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={() => setMore(!more)}>
              {more ? "Menos casos" : "Más casos"}
            </Button>
          </div>
          {more && (
            <div className="flex flex-wrap gap-2">
              {extra.map((c) => (
                <Button key={c.id} variant={selected === c.id ? "default" : "outline"} size="sm" onClick={() => setSelected(c.id)}>
                  {c.nombre}
                </Button>
              ))}
              <Button variant={selected === "pegar" ? "default" : "outline"} size="sm" onClick={() => setSelected("pegar")}>
                Pegar código
              </Button>
            </div>
          )}
          {selected === "pegar" ? (
            <Textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={10}
              className="font-mono text-sm" placeholder="Pega aquí tu script de Python" />
          ) : (
            <pre className="max-h-80 overflow-auto rounded-lg border bg-muted/40 p-5 font-mono text-sm">{code}</pre>
          )}
          <div className="space-y-2">
            <Label htmlFor="video-demo">Enlace de Google Drive al video demo (opcional)</Label>
            <Input id="video-demo" type="url" maxLength={1000} value={video} disabled={busy} onChange={(e) => setVideo(e.target.value)} placeholder="https://drive.google.com/file/d/…/view" />
            <p className="text-xs text-muted-foreground">Compártelo como &apos;cualquier persona con el enlace&apos; y que dure máximo 3 minutos. El video no condiciona un pago aprobado por el motor.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={send} disabled={busy || !!blocked || !code.trim()} data-testid="enviar">
              {busy ? "Enviando…" : "Enviar"}
            </Button>
            {blocked && <span className="text-sm text-muted-foreground">{blocked}</span>}
          </div>
        </CardContent>
      </Card>
      {task.latest_rejected && task.latest_code_hash && task.onchain?.status !== "Released" && (
        <Card className="order-4"><CardHeader><CardTitle>Revisión del cliente</CardTitle>
          <CardDescription>Tu código sigue protegido. Puedes compartir esta entrega rechazada antes de cobrar para que el cliente decida si la aprueba manualmente.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {(consentFor === task.latest_code_hash || task.consented_code_hash === task.latest_code_hash) ? <p role="status">Autorizaste compartir esta entrega. Las entregas futuras requieren otro consentimiento.</p> : <>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />Entiendo que el cliente podrá ver y copiar este código antes de pagar. La autorización de esta entrega no se puede retirar.</label>
              <Button variant="outline" disabled={!checked || consenting || busy} onClick={async () => {
                setConsenting(true); setConsentError(null);
                try { await api.consent(task.task_id, mine.freelancer_token, task.latest_code_hash!); setConsentFor(task.latest_code_hash!); setChecked(false); onDone(); }
                catch (e) { setConsentError(e instanceof Error ? e.message : String(e)); }
                finally { setConsenting(false); }
              }}>{consenting ? "Autorizando…" : "Autorizar revisión de este código"}</Button>
            </>}
            {consentError && <p role="alert" className="text-sm text-[var(--alert-foreground)]">{consentError}</p>}
          </CardContent></Card>
      )}
    </div>
  );
}
