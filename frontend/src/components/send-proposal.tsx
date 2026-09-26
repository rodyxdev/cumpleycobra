"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { Check, Send } from "lucide-react";
import { dropSessionIfRejected, useIdentity } from "@/components/identity";
import { Money } from "@/components/money";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useWallet } from "@/hooks/use-wallet";
import { api, type TaskView } from "@/lib/api";
import { type Session } from "@/lib/identity";
import { taskAvailableForProposal } from "@/lib/proposals";
import { keys, store, useStored } from "@/lib/store";

export function SendProposal({ programador }: { programador: string }) {
  const wallet = useWallet();
  const { session } = useIdentity(wallet.address);
  // El dueño del perfil no se envía propuestas a sí mismo (el backend también lo rechaza).
  return session && session.address !== programador ? <ProposalForm key={`${session.address}:${programador}`} session={session} programador={programador} /> : null;
}

function ProposalForm({ session, programador }: { session: Session; programador: string }) {
  const ids = useStored<string[]>(keys.clientTaskIds);
  const [open, setOpen] = useState(false);
  const [tasks, setTasks] = useState<TaskView[] | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const ownIds = (ids ?? []).filter((id) => store.clientTask(id)?.client_address === session.address);
    Promise.allSettled(ownIds.map((id) => api.task(id))).then((results) => {
      if (!alive) return;
      setTasks(results.flatMap((r) => r.status === "fulfilled" && taskAvailableForProposal(r.value, session.address) ? [r.value] : []));
      if (results.some((r) => r.status === "rejected")) setError("No se pudieron consultar algunas tareas. Vuelve a abrir el formulario para reintentar.");
    });
    return () => { alive = false; };
  }, [open, ids, session.address]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const local = store.clientTask(selected);
    if (!local || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.createProposal(selected, programador, local.client_token, session.token);
      setSent(selected);
    } catch (e) {
      dropSessionIfRejected(session.address, e);
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  if (sent) return <Card data-testid="propuesta-enviada"><CardContent className="flex flex-wrap items-center justify-between gap-4">
    <p className="flex items-center gap-2 font-medium"><Check className="size-5 text-primary" aria-hidden="true" />Propuesta enviada</p>
    <Link href={`/cliente?tarea=${encodeURIComponent(sent)}`} className="text-primary underline-offset-4 hover:underline">Ver el estado de la propuesta</Link>
  </CardContent></Card>;

  const task = tasks?.find((t) => t.task_id === selected);
  return <Card>
    <CardHeader>
      <CardTitle>Trabaja con este programador</CardTitle>
      <CardDescription>Envíale uno de tus pedidos. Podrá revisar los criterios y decidir desde su buzón.</CardDescription>
    </CardHeader>
    <CardContent>
      {!open ? <Button data-testid="enviar-propuesta" onClick={() => { setOpen(true); setTasks(null); setError(null); }}><Send aria-hidden="true" />Enviar propuesta</Button> : (
        <form onSubmit={submit} className="space-y-5" data-testid="form-propuesta">
          <div className="space-y-2">
            <label htmlFor="propuesta-tarea" className="block font-medium">Elige una tarea</label>
            <p id="propuesta-ayuda" className="text-sm text-muted-foreground">Solo tus tareas creadas en este navegador que todavía nadie ha aceptado.</p>
            <select id="propuesta-tarea" aria-describedby="propuesta-ayuda" required value={selected} onChange={(e) => setSelected(e.target.value)} disabled={busy || !tasks?.length}
              className="h-12 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <option value="">{tasks === null ? "Consultando tus tareas…" : "Selecciona una tarea"}</option>
              {tasks?.map((t) => <option key={t.task_id} value={t.task_id}>{t.task_id} · {t.description}</option>)}
            </select>
          </div>
          {tasks?.length === 0 && <p className="text-muted-foreground">No hay tareas disponibles. <Link href="/cliente" className="text-primary underline">Crea un pedido</Link> para enviar una propuesta.</p>}
          {task && <div className="space-y-3 rounded-lg border bg-muted/40 p-4">
            <p>{task.description}</p><p className="text-sm text-muted-foreground">{task.criteria.length} criterios acordados · <Money units={task.onchain?.amount ?? task.amount} inline /></p>
          </div>}
          {error && <p role="alert" className="text-[var(--alert-foreground)]">{error}</p>}
          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={busy || !task} data-testid="confirmar-propuesta">{busy ? "Enviando propuesta…" : "Enviar propuesta"}</Button>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)}>Cancelar</Button>
          </div>
        </form>
      )}
    </CardContent>
  </Card>;
}
