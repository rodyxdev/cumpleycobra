import { Stars } from "@/components/stars";
import type { ProgrammerSummary } from "@/lib/api";
import { ratingLabel } from "@/lib/reputation";

/** Métricas del programador, todas de tareas Released confirmadas en el contrato. */
export function ProgrammerMetrics({ p, compact = false }: { p: ProgrammerSummary; compact?: boolean }) {
  const items = [
    { label: "Tareas verificadas por el motor", value: String(p.engine_paid), testid: "metrica-motor" },
    { label: "Pagadas por aprobación manual", value: String(p.manual_paid), testid: "metrica-manual" },
    { label: "Clientes distintos", value: String(p.distinct_clients), testid: "metrica-clientes" },
  ];
  return (
    <dl className={`grid gap-5 ${compact ? "grid-cols-2 sm:grid-cols-4" : "sm:grid-cols-2 lg:grid-cols-4"}`}>
      {items.map((m) => (
        <div key={m.label} className="space-y-1" data-testid={m.testid}>
          <dt className="text-sm text-muted-foreground">{m.label}</dt>
          <dd className={`${compact ? "text-2xl" : "text-4xl"} font-semibold tabular-nums tracking-[-0.04em]`}>{m.value}</dd>
        </div>
      ))}
      <div className="space-y-1" data-testid="metrica-calificacion">
        <dt className="text-sm text-muted-foreground">Calificación</dt>
        <dd className="space-y-1">
          {p.rating_count > 0 && p.rating_average !== null && <Stars value={p.rating_average} size={compact ? "size-4" : "size-5"} />}
          <span className="block text-sm text-muted-foreground">{ratingLabel(p.rating_average, p.rating_count)}</span>
        </dd>
      </div>
    </dl>
  );
}
