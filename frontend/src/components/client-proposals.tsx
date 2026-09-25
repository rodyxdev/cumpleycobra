"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { dropSessionIfRejected, useIdentity } from "@/components/identity";
import { ProposalStatus } from "@/components/proposal-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useWallet } from "@/hooks/use-wallet";
import { api } from "@/lib/api";
import { shortHash } from "@/lib/format";
import { type Proposal } from "@/lib/proposals";

type Props = { taskId: string; clientToken: string; clientAddress: string };
export function ClientProposals(props: Props) {
  const wallet = useWallet();
  const { session } = useIdentity(wallet.address);
  return session && session.address === props.clientAddress
    ? <ProposalList key={`${props.taskId}:${session.token}`} {...props} sessionToken={session.token} /> : null;
}
function ProposalList({ taskId, clientToken, clientAddress, sessionToken }: Props & { sessionToken: string }) {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const data = await api.taskProposals(taskId, clientToken, sessionToken);
        if (alive) { setProposals(data.propuestas); setError(null); }
      } catch (e) {
        if (alive) { dropSessionIfRejected(clientAddress, e); setError(e instanceof Error ? e.message : String(e)); }
      } finally { if (alive) timer = setTimeout(load, 5000); }
    }
    void load();
    return () => { alive = false; clearTimeout(timer); };
  }, [taskId, clientToken, clientAddress, sessionToken]);
  if (!proposals.length && !error) return null;
  return <Card data-testid="propuestas-cliente">
    <CardHeader><CardTitle>Propuestas enviadas</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      {error && <p role="alert" className="text-[var(--alert-foreground)]">{error}</p>}
      <ul className="divide-y">
        {proposals.map((p) => <li key={p.id} data-proposal-id={p.id} className="flex flex-wrap items-center justify-between gap-3 py-4 first:pt-0 last:pb-0">
          <Link href={`/programador/${p.programador}`} title={p.programador} className="font-mono text-sm text-primary underline-offset-4 hover:underline">{shortHash(p.programador, 10)}</Link>
          <ProposalStatus state={p.estado} />
        </li>)}
      </ul>
    </CardContent>
  </Card>;
}
