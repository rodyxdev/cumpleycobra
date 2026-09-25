import { ChevronDown } from "lucide-react";

import { Terminal } from "@/components/terminal";
import { VerdictCard } from "@/components/verdict-card";

type Props = Parameters<typeof Terminal>[0] & { busy: boolean; amount?: number; criteriaCount: number };

/** Proyección visual de la salida existente; no guarda estado ni vuelve a evaluar el código. */
export function SubmissionResult({ lines, now, busy, amount, criteriaCount }: Props) {
  if (lines.length === 0) return null;
  const last = lines.at(-1);
  const complete = !!last && (last.kind === "link" ||
    (last.kind === "muted" && last.text === "Sin pago: transaction_hash = null"));
  // El pie emitido por useTerminal tiene cinco líneas sin pago y seis con pago.
  // Se lee ese pie, nunca una frase parecida dentro de la traza del modelo.
  const statusIndex = complete ? lines.length - (last.kind === "link" ? 6 : 5) : -1;
  const status = lines[statusIndex];
  const reason = lines[statusIndex + 1];
  const transaction = last?.kind === "link" ? last : null;
  // comparison cierra analysis en el motor. Se toman sus últimas marcas para no repetir trazas.
  const comparison = lines.slice(0, Math.max(0, statusIndex))
    .flatMap((line) => "text" in line && /^[✓✗]/.test(line.text.trimStart()) ? [line.text] : []).slice(-criteriaCount);
  const flags = lines.flatMap((line) => line.kind === "warn" && line.text.startsWith("Alerta de seguridad: ") ? [line.text.slice("Alerta de seguridad: ".length)] : []);
  return (
    <div className="order-first min-w-0 space-y-5">
      {complete && status && "text" in status && reason && "text" in reason && (
        <VerdictCard approved={status.text === "Veredicto: APROBADO"} reason={reason.text}
          comparison={comparison} securityFlags={flags} amount={amount}
          transactionHash={transaction && "text" in transaction ? transaction.text.replace(/^Transacción /, "") : null} />
      )}
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
