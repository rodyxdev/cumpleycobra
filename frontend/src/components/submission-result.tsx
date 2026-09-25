import { ChevronDown } from "lucide-react";

import { Terminal } from "@/components/terminal";
import { VerdictCard } from "@/components/verdict-card";
import type { Verdict } from "@/lib/api";
import { verdictCardProps } from "@/lib/verdict-view";

type Props = Parameters<typeof Terminal>[0] & { busy: boolean; amount?: number; verdict: Verdict | null };

/** Tarjeta con el veredicto que devolvió /evaluate y, debajo, la terminal con el análisis. */
export function SubmissionResult({ lines, now, busy, amount, verdict }: Props) {
  if (lines.length === 0) return null;
  // run() devuelve el veredicto al terminar de imprimir: la tarjeta aparece al mismo tiempo que antes.
  const complete = verdict !== null && !busy;
  return (
    <div className="order-first min-w-0 space-y-5">
      {complete && <VerdictCard {...verdictCardProps(verdict)} amount={amount} />}
      <details key={complete ? "complete" : "reading"} open={!complete} className="analysis-disclosure">
        <summary>
          <span>Ver análisis del motor</span>
          <span className="flex items-center gap-3">
            {busy && <span className="text-sm font-normal text-muted-foreground">En curso</span>}
            <ChevronDown className="disclosure-chevron size-5 text-muted-foreground" aria-hidden="true" />
          </span>
        </summary>
        <Terminal lines={lines} now={now} />
      </details>
    </div>
  );
}
