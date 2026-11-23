import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Interface, Spec } from "@/lib/api";

/** `interface` (verificación por ejecución) es parte del acuerdo: el programador la ve ANTES de aceptar. */
export function CriteriaCard({ spec, title = "Criterios acordados" }: { spec: Spec & { interface?: Interface | null }; title?: string }) {
  const symbols = spec.interface?.symbols ?? [];
  const pages = spec.web?.pages ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{spec.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="divide-y divide-border">
          {spec.criteria.map((c, i) => (
            <li key={i} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
              <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-border text-sm font-medium text-muted-foreground">
                {i + 1}
              </span>
              <span>{c}</span>
            </li>
          ))}
        </ol>
        {spec.examples.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-sm font-medium text-muted-foreground">Ejemplos acordados</div>
            <div className="rounded-md border bg-muted/40 p-4 font-mono text-sm leading-relaxed">
              {spec.examples.map((e, i) => (
                <div key={i}>
                  {e.input} <span className="text-muted-foreground">→</span> {e.output}
                </div>
              ))}
            </div>
          </div>
        )}
        {symbols.length > 0 && (
          <div className="space-y-1.5" data-testid="interfaz-acordada">
            <div className="text-sm font-medium text-muted-foreground">Lo que tu entrega debe exponer</div>
            <div className="space-y-2 rounded-md border bg-muted/40 p-4 text-sm">
              {symbols.map((sym) => (
                <div key={`${sym.module}.${sym.name}`} className="space-y-0.5">
                  <div className="text-muted-foreground">En el archivo <span className="font-mono text-foreground">{sym.module.replaceAll(".", "/")}.py</span>:</div>
                  <div className="break-all font-mono">{sym.signature}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        {pages.length > 0 && (
          <div className="text-sm text-muted-foreground">
            Páginas que se revisan en el navegador: <span className="font-mono text-foreground">{pages.join(", ")}</span>
          </div>
        )}
        <div className="text-sm text-muted-foreground">
          Lenguaje: {spec.language} · Dependencias permitidas:{" "}
          {spec.allowed_deps.length ? spec.allowed_deps.join(", ") : "ninguna"}
        </div>
      </CardContent>
    </Card>
  );
}
