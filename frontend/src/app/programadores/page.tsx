"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, CloudOff, Users } from "lucide-react";

import { EmptyState } from "@/components/empty-state";

import { IdentityBadge } from "@/components/identity";
import { ProgrammerMetrics } from "@/components/programmer-metrics";
import { SkillTags } from "@/components/skill-tags";
import { Card, CardContent } from "@/components/ui/card";
import { api, ApiError, type ProgrammerSummary } from "@/lib/api";
import { loadProblem } from "@/lib/load-problem";
import { shortHash } from "@/lib/format";

export default function ProgramadoresPage() {
  const [list, setList] = useState<ProgrammerSummary[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    api.programmers().then(
      (r) => { if (alive) { setList(r.programmers); setError(null); } },
      (e) => { if (alive) setError(e instanceof ApiError ? e : new ApiError(0, "ERROR", String(e))); },
    );
    return () => { alive = false; };
  }, [attempt]);
  const problem = error ? loadProblem(error.code, error.status, error.message) : null;
  // Fallas pasajeras (red, RPC): se reintenta sola cada 5 s, como promete el mensaje.
  const transient = !list && !!problem?.transient;
  useEffect(() => {
    if (!transient) return;
    const id = setTimeout(() => setAttempt((n) => n + 1), 5000);
    return () => clearTimeout(id);
  }, [transient, attempt]);

  return (
    <div className="space-y-8">
      <div className="page-heading">
        <h1>Programadores</h1>
        <p className="text-muted-foreground">
          Reputación verificable: solo cuentan las tareas que el contrato registra como pagadas. Ordenados por tareas
          verificadas por el motor.
        </p>
      </div>

      {problem && !list && (
        <EmptyState icon={CloudOff} title={problem.title} testId="programadores-error"
          actions={[{ label: "Intentar de nuevo", onClick: () => { setError(null); setAttempt((n) => n + 1); }, primary: true }, { label: "Ir al inicio", href: "/" }]}>
          {problem.text}
        </EmptyState>
      )}
      {!error && !list && <p className="text-base text-muted-foreground">Leyendo las tareas pagadas en el contrato…</p>}
      {list && list.length === 0 && (
        <EmptyState icon={Users} title="Todavía no hay tareas verificadas" testId="sin-programadores"
          actions={[{ label: "Crear la primera tarea", href: "/cliente", primary: true }]}>
          Un programador aparece aquí cuando el contrato registra su primer pago. La reputación no se puede escribir a
          mano: sale de los pagos en Stellar.
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <ol className="space-y-4" data-testid="lista-programadores">
          {list.map((p) => (
            <li key={p.address}>
              <Card>
                <CardContent className="space-y-5">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-3">
                      <Link href={`/programador/${p.address}`}
                        className={`group inline-flex items-center gap-2 text-lg font-medium text-primary underline-offset-4 hover:underline ${p.nombre ? "" : "font-mono"}`}
                        title={p.address}>
                        {p.nombre ?? shortHash(p.address, 10)}
                        <ArrowRight className="size-4" aria-hidden="true" />
                      </Link>
                      {p.identidad_verificada && <IdentityBadge />}
                    </div>
                    {p.nombre && <p className="font-mono text-sm text-muted-foreground">{shortHash(p.address, 10)}</p>}
                    {!!p.habilidades?.length && <SkillTags skills={p.habilidades} />}
                  </div>
                  <ProgrammerMetrics p={p} compact />
                </CardContent>
              </Card>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
