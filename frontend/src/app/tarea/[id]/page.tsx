"use client";

import { use, useEffect, useState } from "react";

import { CriteriaCard } from "@/components/criteria-card";
import { StatusCard } from "@/components/status-card";
import { Terminal, useTerminal } from "@/components/terminal";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useTask } from "@/hooks/use-task";
import { api, ApiError, type Caso, type TaskView } from "@/lib/api";
import { isStellarAddress } from "@/lib/format";
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

  if (!task) {
    return <p className="text-sm text-muted-foreground">{error ? error.message : "Cargando la tarea…"}</p>;
  }

  const accepted = mine && task.freelancer_address === mine.freelancer_address;
  const takenByOther = task.freelancer_address && !accepted;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Vista del programador</h1>
        <p className="text-sm text-muted-foreground">
          Tarea {id}. Estos son los criterios que el motor va a verificar; el monto es el que está en el contrato.
        </p>
      </div>
      <StatusCard task={task} secondsLeft={secondsLeft} />
      <CriteriaCard spec={task} />
      {accepted ? (
        <SubmitPanel task={task} mine={mine} secondsLeft={secondsLeft} onDone={refresh} />
      ) : takenByOther ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">Esta tarea ya la aceptó otro programador.</CardContent>
        </Card>
      ) : (
        <AcceptPanel taskId={id} invite={invitacion ?? null} onAccepted={refresh} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aceptar criterios
// ---------------------------------------------------------------------------
function AcceptPanel({ taskId, invite, onAccepted }: { taskId: string; invite: string | null; onAccepted: () => void }) {
  const stored = useStored<string>(keys.lastAddress("programador"));
  const [address, setAddress] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [sending, setSending] = useState(false);
  const addr = (address ?? stored ?? "").trim();

  async function accept() {
    if (!invite) return;
    setSending(true);
    setError(null);
    try {
      const { freelancer_token } = await api.accept(taskId, addr, invite);
      store.saveFreelancerTask({ task_id: taskId, freelancer_token, freelancer_address: addr });
      store.saveLastAddress("programador", addr);
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
          Al aceptar, la tarea queda amarrada a tu dirección: el pago solo puede ir a ella. La conexión con la wallet
          llega en la siguiente fase; por ahora escribe tu dirección.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!invite && (
          <p className="text-sm text-red-600">Necesitas el enlace de invitación que te compartió el cliente.</p>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="programador">Tu dirección de Stellar (G…)</Label>
          <Input id="programador" value={addr} placeholder="G…" className="font-mono text-xs"
            onChange={(e) => setAddress(e.target.value)} />
        </div>
        {error?.code === "NO_USDC_TRUSTLINE" ? (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <div className="font-medium">Activa USDC antes de continuar</div>
            Tu cuenta no tiene trustline de USDC, así que no podría recibir el pago. Actívala y vuelve a aceptar.
          </div>
        ) : error ? (
          <p className="text-sm text-red-600">{error.message}</p>
        ) : null}
        <Button disabled={!invite || !isStellarAddress(addr) || sending} onClick={accept}>
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
  const [more, setMore] = useState(false);
  const [pasted, setPasted] = useState("");
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
    await run(label, () => api.evaluate(task.task_id, mine.freelancer_address, code, mine.freelancer_token));
    onDone();
  }

  const principales = casos.filter((c) => c.principal);
  const extra = casos.filter((c) => !c.principal);

  return (
    <div className="space-y-4">
      <Card>
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
              className="font-mono text-xs" placeholder="Pega aquí tu script de Python" />
          ) : (
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">{code}</pre>
          )}
          <div className="flex items-center gap-3">
            <Button onClick={send} disabled={busy || !!blocked || !code.trim()} data-testid="enviar">
              {busy ? "Enviando…" : "Enviar"}
            </Button>
            {blocked && <span className="text-sm text-muted-foreground">{blocked}</span>}
          </div>
        </CardContent>
      </Card>
      <Terminal lines={lines} now={now} />
    </div>
  );
}
