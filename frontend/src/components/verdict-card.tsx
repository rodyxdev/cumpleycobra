import type { ReactNode } from "react";
import { ArrowUpRight, Check, ShieldAlert, X } from "lucide-react";

import { ComparisonList } from "@/components/comparison-list";
import { Money, FxNotice } from "@/components/money";
import { Card, CardContent } from "@/components/ui/card";
import { explorerTx, shortHash } from "@/lib/format";

type VerdictCardProps = {
  approved: boolean;
  reason: string;
  comparison: string[];
  securityFlags?: string[];
  transactionHash: string | null;
  amount?: number;
  meta?: ReactNode;
  children?: ReactNode;
};

/** Presentación compartida: recibe únicamente los datos disponibles para cada vista. */
export function VerdictCard({ approved, reason, comparison, securityFlags = [], transactionHash, amount, meta, children }: VerdictCardProps) {
  const paid = approved && !!transactionHash;
  const Icon = approved ? Check : X;
  return (
    <Card className="relative ring-1 ring-border" aria-label="Veredicto">
      <div className={`absolute inset-y-0 left-0 w-1 ${approved ? "bg-primary" : "bg-[var(--alert)]"}`} />
      <CardContent className="space-y-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <p className="eyebrow">Resultado de la entrega</p>
            <h2 className="text-3xl font-semibold tracking-[-0.04em]">Veredicto</h2>
          </div>
          <span className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-base font-semibold ${approved ? "bg-secondary text-primary" : "bg-[var(--alert-background)] text-[var(--alert-foreground)]"}`}>
            <Icon className="size-5" aria-hidden="true" />
            {paid ? "Aprobado y pagado" : approved ? "Aprobado · sin pago" : "Rechazado"}
          </span>
        </div>
        <p className="max-w-4xl text-lg leading-relaxed">{reason}</p>
        {securityFlags.length > 0 && (
          <div className="alert-panel flex items-start gap-3" role="note" aria-label="Aviso de seguridad">
            <ShieldAlert className="mt-1 size-5 shrink-0" aria-hidden="true" />
            <div className="space-y-2">
              <h3 className="font-semibold">Aviso de seguridad</h3>
              <ul className="list-disc space-y-1 pl-5 text-base">
                {securityFlags.map((flag, i) => <li key={i}>{flag}</li>)}
              </ul>
            </div>
          </div>
        )}
        {comparison.length > 0 && <section className="space-y-4" aria-label="Resultado por criterio">
          <h3 className="eyebrow">Criterios acordados</h3>
          <ComparisonList items={comparison} />
        </section>}
        {paid && <div className="space-y-4 border-t pt-6">
          <div className="flex flex-wrap items-center justify-between gap-5">
            <div className="space-y-2">
              <p className="eyebrow">Pago liberado</p>
              {amount !== undefined && <div className="money-prominent"><Money units={amount} /></div>}
            </div>
            <a className="group inline-flex items-center gap-3 rounded-lg border border-primary/30 px-4 py-3 text-base font-medium text-primary hover:bg-secondary" href={explorerTx(transactionHash!)} target="_blank" rel="noreferrer">
              <span>Ver transacción <span className="mt-0.5 block font-mono text-sm font-normal">{shortHash(transactionHash!, 8)}</span></span>
              <ArrowUpRight className="size-5" aria-hidden="true" />
            </a>
          </div>
          <FxNotice />
        </div>}
        {meta && <div className="border-t pt-4 text-sm text-muted-foreground">{meta}</div>}
        {children}
      </CardContent>
    </Card>
  );
}
