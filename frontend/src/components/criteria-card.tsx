import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Spec } from "@/lib/api";

export function CriteriaCard({ spec, title = "Criterios acordados" }: { spec: Spec; title?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{spec.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="space-y-2">
          {spec.criteria.map((c, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
                {i + 1}
              </span>
              <span>{c}</span>
            </li>
          ))}
        </ol>
        {spec.examples.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">Ejemplos acordados</div>
            <div className="rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
              {spec.examples.map((e, i) => (
                <div key={i}>
                  {e.input} <span className="text-muted-foreground">→</span> {e.output}
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          Lenguaje: {spec.language} · Dependencias permitidas:{" "}
          {spec.allowed_deps.length ? spec.allowed_deps.join(", ") : "ninguna"}
        </div>
      </CardContent>
    </Card>
  );
}
