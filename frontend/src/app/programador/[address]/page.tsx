"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowUpRight, ShieldCheck } from "lucide-react";

import { Money } from "@/components/money";
import { IdentityBadge } from "@/components/identity";
import { ProfileEditor } from "@/components/profile-editor";
import { ProgrammerMetrics } from "@/components/programmer-metrics";
import { SkillTags } from "@/components/skill-tags";
import { Stars } from "@/components/stars";
import { Card, CardContent } from "@/components/ui/card";
import { api, ApiError, type ProgrammerProfile } from "@/lib/api";
import { explorerTx, shortHash } from "@/lib/format";
import { HONEST_NOTE, paidByLabel, paidDate } from "@/lib/reputation";

export default function ProgramadorPage({ params }: { params: Promise<{ address: string }> }) {
  const { address } = use(params);
  const [profile, setProfile] = useState<ProgrammerProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.programmer(address).then(
      (p) => { if (alive) setProfile(p); },
      (e) => { if (alive) setError(e instanceof ApiError ? e.message : String(e)); },
    );
    return () => { alive = false; };
  }, [address]);

  return (
    <div className="space-y-8">
      <div className="page-heading">
        <p className="eyebrow">Perfil del programador</p>
        {profile?.nombre ? (
          <h1 data-testid="perfil-nombre">{profile.nombre}</h1>
        ) : (
          <h1 className="break-all font-mono text-2xl sm:text-3xl" title={address}>{shortHash(address, 10)}</h1>
        )}
        <p className="break-all font-mono text-sm text-muted-foreground">{address}</p>
        {profile?.identidad_verificada && <div><IdentityBadge /></div>}
        {!!profile?.habilidades?.length && <SkillTags skills={profile.habilidades} />}
        {profile?.bio && <p className="text-base" data-testid="perfil-bio">{profile.bio}</p>}
      </div>

      {error && <p role="alert" className="text-base text-[var(--alert-foreground)]">{error}</p>}
      {!error && !profile && <p className="text-base text-muted-foreground">Cargando el perfil desde el contrato…</p>}

      {profile && (
        <>
          <ProfileEditor address={address}
            initial={{ nombre: profile.nombre ?? null, habilidades: profile.habilidades ?? [], bio: profile.bio ?? null }}
            onSaved={(p) => setProfile({ ...profile, ...p, identidad_verificada: true })} />
          <Card>
            <CardContent className="space-y-6">
              <ProgrammerMetrics p={profile} />
              <p className="flex items-start gap-3 border-t pt-5 text-sm text-muted-foreground" data-testid="nota-honesta">
                <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                {HONEST_NOTE}
              </p>
            </CardContent>
          </Card>

          <section className="space-y-4" aria-label="Historial de tareas pagadas">
            <h2 className="eyebrow">Historial</h2>
            {profile.history.length === 0 ? (
              <Card><CardContent className="text-base text-muted-foreground" data-testid="sin-tareas">
                Todavía no hay tareas verificadas.
              </CardContent></Card>
            ) : (
              <ol className="space-y-4" data-testid="historial">
                {profile.history.map((t) => (
                  <li key={t.task_id}>
                    <Card>
                      <CardContent className="space-y-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <span className={`rounded-full px-3 py-1 text-sm font-semibold ${t.paid_by === "motor" ? "bg-secondary text-primary" : "bg-muted text-foreground"}`}>
                            {paidByLabel(t.paid_by)}
                          </span>
                          <span className="text-sm text-muted-foreground">{paidDate(t.paid_at)} · tarea <span className="font-mono">{t.task_id}</span></span>
                        </div>
                        <p className="text-lg leading-relaxed">{t.description}</p>
                        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-base text-muted-foreground">
                          <span>{t.criteria_count} {t.criteria_count === 1 ? "criterio acordado" : "criterios acordados"}</span>
                          <span className="text-foreground"><Money units={t.amount} inline /></span>
                        </div>
                        {t.rating && (
                          <div className="space-y-1 border-t pt-4">
                            <Stars value={t.rating.estrellas} />
                            {t.rating.comentario && <p className="text-base text-muted-foreground">«{t.rating.comentario}»</p>}
                          </div>
                        )}
                        <div className="border-t pt-4">
                          {t.transaction_hash ? (
                            <a href={explorerTx(t.transaction_hash)} target="_blank" rel="noreferrer"
                              className="inline-flex items-center gap-2 text-base font-medium text-primary underline-offset-4 hover:underline">
                              Ver el pago en el explorador <span className="font-mono text-sm">{shortHash(t.transaction_hash, 8)}</span>
                              <ArrowUpRight className="size-4" aria-hidden="true" />
                            </a>
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              Pago confirmado en el contrato; su transacción ya no está en la ventana de consulta del RPC.
                            </p>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <Link href="/programadores" className="text-base text-primary underline-offset-4 hover:underline">
            Ver todos los programadores
          </Link>
        </>
      )}
    </div>
  );
}
