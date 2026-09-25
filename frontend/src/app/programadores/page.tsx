"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";

import { IdentityBadge } from "@/components/identity";
import { ProgrammerMetrics } from "@/components/programmer-metrics";
import { SkillTags } from "@/components/skill-tags";
import { Card, CardContent } from "@/components/ui/card";
import { api, ApiError, type ProgrammerSummary } from "@/lib/api";
import { shortHash } from "@/lib/format";

export default function ProgramadoresPage() {
  const [list, setList] = useState<ProgrammerSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.programmers().then(
      (r) => { if (alive) setList(r.programmers); },
      (e) => { if (alive) setError(e instanceof ApiError ? e.message : String(e)); },
    );
    return () => { alive = false; };
  }, []);

  return (
    <div className="space-y-8">
      <div className="page-heading">
        <h1>Programadores</h1>
        <p className="text-muted-foreground">
          Reputación verificable: solo cuentan las tareas que el contrato registra como pagadas. Ordenados por tareas
          verificadas por el motor.
        </p>
      </div>

      {error && <p role="alert" className="text-base text-[var(--alert-foreground)]">{error}</p>}
      {!error && !list && <p className="text-base text-muted-foreground">Leyendo las tareas pagadas en el contrato…</p>}
      {list && list.length === 0 && (
        <Card><CardContent className="text-base text-muted-foreground" data-testid="sin-programadores">
          Todavía no hay tareas verificadas.
        </CardContent></Card>
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
