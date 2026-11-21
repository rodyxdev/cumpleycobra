import { Check, Clock } from "lucide-react";

import type { TaskView } from "@/lib/api";
import { formatCountdown, STATUS_LABEL } from "@/lib/format";
import { Money, FxNotice } from "@/components/money";

type Step = { name: string; detail: string; done: boolean };

/** Pasos de la tarea, deducidos solo de lo que reporta la API y el contrato. */
export function taskSteps(task: TaskView): Step[] {
  const status = task.onchain?.status;
  const refunded = status === "Refunded";
  const released = status === "Released";
  return [
    { name: "Acuerdo", detail: "Criterios finales del cliente", done: true },
    { name: "Depósito", detail: "USDC en el contrato", done: !!task.onchain },
    { name: "Aceptado", detail: "El programador aceptó los criterios", done: !!task.freelancer_address },
    { name: "Verificado", detail: "Veredicto por criterio", done: task.submissions_used > 0 || released },
    refunded
      ? { name: "Reembolsado", detail: "El USDC volvió al cliente", done: true }
      : { name: "Pagado", detail: "USDC en la wallet del programador", done: released },
  ];
}

function TaskTimeline({ task }: { task: TaskView }) {
  const steps = taskSteps(task);
  const current = steps.findIndex((s) => !s.done);
  return (
    <ol className="grid grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-3 lg:grid-cols-5" aria-label="Línea de estado de la tarea">
      {steps.map((s, i) => {
        const active = i === current;
        return (
          <li key={s.name} aria-current={active ? "step" : undefined} className="flex flex-col gap-2.5">
            <div className="flex items-center gap-2">
              <span className={`flex size-9 shrink-0 items-center justify-center rounded-full border-2 text-sm font-extrabold ${
                s.done ? "border-success bg-success text-white"
                  : active ? "border-primary bg-card text-primary" : "border-border bg-muted text-muted-foreground"}`}>
                {s.done ? <Check className="size-4" strokeWidth={3.5} aria-hidden="true" /> : i + 1}
                <span className="sr-only">{s.done ? "Hecho:" : active ? "En curso:" : "Pendiente:"}</span>
              </span>
              {i < steps.length - 1 && <span className={`hidden h-[3px] flex-1 rounded-full lg:block ${s.done ? "bg-success" : "bg-border"}`} aria-hidden="true" />}
            </div>
            <span className={`text-[0.95rem] font-bold ${active ? "text-primary" : ""}`}>{s.name}</span>
            <span className="text-[0.8rem] leading-snug text-muted-foreground">{s.detail}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Línea de estado, monto leído del contrato y cuenta regresiva del plazo. */
export function StatusCard({ task, secondsLeft }: { task: TaskView; secondsLeft: number | null }) {
  const onchain = task.onchain;
  const status = onchain?.status;
  const tone = status === "Released" ? "text-success-strong" : status === "Funded" ? "text-primary" : "text-muted-foreground";
  return (
    <div className="space-y-4">
      <section className="surface p-5 sm:p-7"><TaskTimeline task={task} /></section>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-[1fr_1.35fr_1fr_.8fr]">
        <div className="surface space-y-2 p-5">
          <p className="text-sm text-muted-foreground">Estado en el contrato</p>
          <div className={`brand-heading flex items-center gap-2 text-2xl ${tone}`} data-testid="estado">
            <span className="size-2.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
            {onchain ? STATUS_LABEL[onchain.status] ?? onchain.status : "Sin depósito"}
          </div>
        </div>
        <div className="surface space-y-2 p-5">
          <p className="text-sm text-muted-foreground">Monto en el contrato</p>
          <div className="money-prominent">{onchain ? <Money units={onchain.amount} /> : "—"}</div>
        </div>
        <div className="surface space-y-2 p-5">
          <p className="text-sm text-muted-foreground">Plazo restante</p>
          <div className="brand-heading flex items-center gap-2 text-2xl tabular-nums" data-testid="plazo">
            <Clock className="size-5 text-muted-foreground" aria-hidden="true" />
            {onchain && status === "Funded" && secondsLeft !== null
              ? secondsLeft > 0 ? formatCountdown(secondsLeft) : "vencido" : "—"}
          </div>
        </div>
        <div className="surface space-y-2 p-5">
          <p className="text-sm text-muted-foreground">Envíos usados</p>
          <p className="brand-heading text-2xl tabular-nums">{task.submissions_used} <span className="text-base font-semibold text-muted-foreground">de {task.max_submissions}</span></p>
        </div>
      </div>
      {task.onchain_error && <p className="alert-panel text-base">No se pudo leer el contrato: {task.onchain_error}</p>}
      <FxNotice />
    </div>
  );
}
