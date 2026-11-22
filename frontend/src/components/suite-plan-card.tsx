import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { SuitePlan } from "@/lib/api";
import { SUITE_STATUS_LABEL, TIPO_LABEL, WEB_SUITE_STATUS_LABEL } from "@/lib/verification";

/** Plan de la suite oculta (fase 3): qué se comprueba ejecutando y qué leyendo. Nunca el código de los tests. */
export function SuitePlanCard({ suite, criteria }: { suite: SuitePlan; criteria: string[] }) {
  const working = suite.status === "pendiente" || suite.status === "validando";
  return (
    <Card data-testid="suite-plan">
      <CardHeader>
        <CardTitle>Cómo se va a verificar</CardTitle>
        <CardDescription>
          {suite.profile === "web"
            ? "El verificador abre el sitio en un navegador real, aislado y sin internet, a 1440 px y a 390 px. Los chequeos son públicos: así se comprueba cada criterio."
            : "El verificador ejecuta la entrega en un contenedor aislado contra una suite de tests oculta. Aquí ves qué comprueba cada test, no su código, para que nadie escriba solo para pasarlos."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p role="status" className={`text-sm font-medium ${suite.status === "rechazada" ? "text-[var(--alert-foreground)]" : working ? "text-muted-foreground" : "text-primary"}`}>
          {(suite.profile === "web" ? WEB_SUITE_STATUS_LABEL : SUITE_STATUS_LABEL)[suite.status]}
          {working ? "… (de 1 a 3 minutos si hay que encender el verificador)" : ""}
        </p>
        {suite.status === "rechazada" && suite.error && (
          <p className="text-sm text-[var(--alert-foreground)]">{suite.error}. Crea la tarea de nuevo para intentarlo otra vez.</p>
        )}
        {suite.status !== "pendiente" && (
          <ol className="divide-y divide-border">
            {suite.criteria.map((c) => (
              <li key={c.index} className="space-y-2 py-4 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-medium">Criterio {c.index}</span>
                  {c.tipo && (
                    <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold text-primary">
                      {TIPO_LABEL[c.tipo] ?? c.tipo}
                    </span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">{criteria[c.index - 1]}</p>
                {c.plan.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {c.plan.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                )}
                {c.problems.length > 0 && <p className="text-sm text-[var(--alert-foreground)]">{c.problems[0]}</p>}
              </li>
            ))}
          </ol>
        )}
        {suite.suite_hash && <p className="break-all font-mono text-xs text-muted-foreground">suite_hash {suite.suite_hash}</p>}
      </CardContent>
    </Card>
  );
}
