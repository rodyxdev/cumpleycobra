"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Inbox } from "lucide-react";
import { dropSessionIfRejected, useIdentity, VerifyIdentityButton } from "@/components/identity";
import { FxNotice, Money } from "@/components/money";
import { ProposalStatus } from "@/components/proposal-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useWallet } from "@/hooks/use-wallet";
import { api } from "@/lib/api";
import { STATUS_LABEL } from "@/lib/format";
import { type Session } from "@/lib/identity";
import { canDecideProposal, type InboxProposal } from "@/lib/proposals";
import { store } from "@/lib/store";

export default function BuzonPage() {
  const wallet = useWallet();
  const { session } = useIdentity(wallet.address);
  return <div className="space-y-8">
    <div className="page-heading"><p className="eyebrow">Tus propuestas</p><h1>Buzón</h1>
      <p>Revisa el pedido y sus criterios antes de aceptar el trabajo.</p>
    </div>
    {!wallet.address ? <Card><CardContent>Inicia sesión con tu wallet para ver tus propuestas.</CardContent></Card> : !session ? (
      <Card><CardContent className="space-y-4"><p>Verifica tu identidad para abrir las propuestas dirigidas a tu wallet.</p><VerifyIdentityButton address={wallet.address} /></CardContent></Card>
    ) : <InboxList key={session.token} session={session} />}
  </div>;
}

function InboxList({ session }: { session: Session }) {
  const router = useRouter();
  const [proposals, setProposals] = useState<InboxProposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const data = await api.inbox(session.token);
        if (alive) { setProposals(data.propuestas); setLoadError(null); }
      } catch (e) {
        if (alive) { dropSessionIfRejected(session.address, e); setLoadError(e instanceof Error ? e.message : String(e)); }
      } finally { if (alive) timer = setTimeout(load, 5000); }
    }
    void load();
    return () => { alive = false; clearTimeout(timer); };
  }, [session.address, session.token]);

  async function decide(p: InboxProposal, action: "accept" | "reject") {
    if (busy) return;
    setBusy(p.id);
    setError(null);
    try {
      if (action === "accept") {
        const result = await api.acceptProposal(p.id, session.token);
        store.saveFreelancerTask({ task_id: p.task_id, freelancer_address: session.address, freelancer_token: result.freelancer_token });
        router.push(`/tarea/${encodeURIComponent(p.task_id)}`);
      } else {
        const result = await api.rejectProposal(p.id, session.token);
        setProposals((items) => items?.map((item) => item.id === p.id ? { ...item, estado: result.estado } : item) ?? null);
      }
    } catch (e) {
      dropSessionIfRejected(session.address, e);
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  }

  return <div className="space-y-5">
    {loadError && <p role="alert" className="text-[var(--alert-foreground)]">{loadError}</p>}
    {error && <p role="alert" className="text-[var(--alert-foreground)]">{error}</p>}
    {proposals === null && !loadError && <p className="text-muted-foreground">Consultando tus propuestas…</p>}
    {proposals?.length === 0 && <Card><CardContent className="space-y-3 py-4" data-testid="buzon-vacio">
      <Inbox className="size-7 text-primary" aria-hidden="true" /><h2 className="text-xl font-semibold">Tu buzón está al día</h2>
      <p className="text-muted-foreground">Aquí aparecerán las propuestas que los clientes envíen a tu dirección.</p>
    </CardContent></Card>}
    {proposals?.map((p) => <Card key={p.id} data-proposal-id={p.id}>
      <CardContent className="space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2"><p className="eyebrow">Tarea <span className="font-mono">{p.task_id}</span></p><ProposalStatus state={p.estado} /></div>
          <div className="text-right"><p className="text-xl font-semibold"><Money units={p.tarea.onchain?.amount ?? p.tarea.amount} /></p>
            <p className="mt-1 text-sm text-muted-foreground">{p.tarea.onchain ? STATUS_LABEL[p.tarea.onchain.status] : p.tarea.onchain_error ? "Estado del contrato no disponible" : "Sin depósito confirmado"}</p>
          </div>
        </div>
        <h2 className="text-xl font-medium leading-relaxed">{p.tarea.description}</h2>
        <div className="space-y-3"><h3 className="eyebrow">Criterios acordados</h3>
          <ol className="divide-y rounded-lg border px-5">{p.tarea.criteria.map((c, i) => <li key={i} className="flex gap-4 py-4"><span className="text-primary" aria-hidden="true">{i + 1}.</span><span>{c}</span></li>)}</ol>
        </div>
        {p.tarea.onchain_error && <p role="alert" className="text-[var(--alert-foreground)]">{p.tarea.onchain_error}</p>}
        {canDecideProposal(p) ? <div className="flex flex-wrap items-center gap-3 border-t pt-5">
          <Button disabled={busy !== null} onClick={() => decide(p, "accept")} data-testid="aceptar-propuesta">Aceptar</Button>
          <Button disabled={busy !== null} variant="outline" onClick={() => decide(p, "reject")} data-testid="rechazar-propuesta">Rechazar</Button>
          {busy === p.id && <span role="status" className="text-sm text-muted-foreground">Guardando tu decisión…</span>}
        </div> : <div className="border-t pt-5">
          {p.estado === "aceptada" ? <Link href={`/tarea/${encodeURIComponent(p.task_id)}`} className="text-primary underline-offset-4 hover:underline">Ver tarea</Link>
            : <p className="text-muted-foreground">{p.estado === "rechazada" ? "Rechazaste esta propuesta." : "Esta tarea ya fue aceptada."}</p>}
        </div>}
      </CardContent>
    </Card>)}
    {!!proposals?.length && <FxNotice />}
  </div>;
}
