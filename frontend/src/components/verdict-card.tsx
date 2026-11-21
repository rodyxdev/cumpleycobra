import type { ReactNode } from "react";
import { ArrowUpRight, Check, ShieldAlert, ShieldCheck, X } from "lucide-react";

import { ComparisonList } from "@/components/comparison-list";
import { Money, FxNotice } from "@/components/money";
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
  const met = comparison.filter((line) => line.trimStart().startsWith("✓")).length;
  const status = paid ? "Aprobado y pagado" : approved ? "Aprobado · sin pago" : "Rechazado";
  return (
    <section className="surface overflow-hidden" aria-label="Veredicto">
      <div className={`h-1.5 ${approved ? "bg-success" : "bg-danger"}`} aria-hidden="true" />
      <div className="grid lg:grid-cols-[1.5fr_1fr]">
        <div className="flex flex-wrap items-start gap-6 p-6 sm:p-8">
          <div className={`flex size-24 shrink-0 items-center justify-center rounded-full ${approved ? "bg-success-soft" : "bg-danger-soft"}`} aria-hidden="true">
            <span className={`flex size-[4.25rem] items-center justify-center rounded-full text-white ${approved ? "bg-success" : "bg-danger"}`}>
              <Icon className="size-9" strokeWidth={3} />
            </span>
          </div>
          <div className="min-w-0 flex-1 basis-72 space-y-3.5">
            {/* Sin text-transform: los ensayos leen innerText y buscan «Rechazado» tal cual. */}
            <p className={`text-base font-bold ${approved ? "text-success-strong" : "text-danger"}`}>{status}</p>
            <h2 className="brand-heading text-3xl leading-tight sm:text-[2.25rem]">{approved ? "Cumple lo acordado" : "No cumple lo acordado"}</h2>
            <p className="max-w-3xl text-base leading-relaxed text-[#2E3A4D] sm:text-lg">{reason}</p>
            {comparison.length > 0 && (
              <p className="inline-flex rounded-full bg-muted px-3 py-1.5 text-sm text-[#2E3A4D]">{met} de {comparison.length} criterios</p>
            )}
          </div>
        </div>
        <div className={`flex flex-col justify-center gap-3 border-t p-6 sm:p-8 lg:border-t-0 lg:border-l ${paid ? "bg-[#F1F8F4]" : "bg-background"}`}>
          {paid ? (
            <>
              <p className="text-sm font-medium text-muted-foreground">Pago liberado al programador</p>
              {amount !== undefined && <div className="money-hero"><Money units={amount} /></div>}
              <a className="inline-flex min-h-12 items-center gap-2 self-start rounded-xl bg-primary px-5 font-bold text-primary-foreground transition-colors hover:bg-navy-deep"
                href={explorerTx(transactionHash!)} target="_blank" rel="noreferrer">
                Ver el pago en Stellar <ArrowUpRight className="size-5" aria-hidden="true" />
              </a>
              <p className="font-mono text-xs text-muted-foreground">tx {shortHash(transactionHash!, 8)}</p>
            </>
          ) : approved ? (
            <>
              <p className="text-sm font-medium text-muted-foreground">Sin pago todavía</p>
              <p className="text-base leading-relaxed">El motor aprobó la entrega, pero el pago no se liberó. El motivo está arriba.</p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-muted-foreground">Sin pago</p>
              <p className="text-base leading-relaxed">El dinero sigue en el contrato. El programador puede volver a enviar, y el cliente puede aprobar a mano.</p>
            </>
          )}
        </div>
      </div>

      <div className="space-y-6 border-t p-6 sm:p-8">
        {securityFlags.length > 0 ? (
          <div className="alert-panel flex items-start gap-3" role="note" aria-label="Aviso de seguridad">
            <ShieldAlert className="mt-1 size-5 shrink-0" aria-hidden="true" />
            <div className="space-y-2">
              <h3 className="font-semibold">Aviso de seguridad</h3>
              <ul className="list-disc space-y-1 pl-5 text-base">
                {securityFlags.map((flag, i) => <li key={i}>{flag}</li>)}
              </ul>
            </div>
          </div>
        ) : (
          <p className="inline-flex items-center gap-2 rounded-lg bg-success-soft px-3 py-2 text-sm font-bold text-success-strong">
            <ShieldCheck className="size-4" aria-hidden="true" />Sin alertas de seguridad
          </p>
        )}
        {comparison.length > 0 && <section className="space-y-4" aria-label="Resultado por criterio">
          <h3 className="text-xl font-bold">Criterio por criterio</h3>
          <ComparisonList items={comparison} />
        </section>}
        {paid && <FxNotice />}
        {meta && <div className="border-t pt-4 text-sm text-muted-foreground">{meta}</div>}
        {children}
      </div>
    </section>
  );
}
