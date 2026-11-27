"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { canonicalJson, objetoAcordado, sha256Hex, type AcuerdoTarea } from "@/lib/acuerdo";
import { api, ApiError, type TaskView } from "@/lib/api";

type HitoVista = { index: number; title: string; criteria: string[]; rules_hash: string; onchain: { rules_hash?: string } | null };
type Fila = { etiqueta: string; local: string; guardado: string; onchain: string | null; canonico: string };

async function revisar(task: TaskView & { milestones?: HitoVista[] }): Promise<Fila[]> {
  const base = task as unknown as AcuerdoTarea;
  if (task.milestones?.length) {
    const de = task.milestones.length;
    return Promise.all(task.milestones.map(async (m) => {
      const canonico = canonicalJson(objetoAcordado(base, { indice: m.index, de, titulo: m.title, criteria: m.criteria }));
      return { etiqueta: `Hito ${m.index + 1}: ${m.title}`, local: await sha256Hex(canonico), guardado: m.rules_hash,
        onchain: m.onchain?.rules_hash ?? null, canonico };
    }));
  }
  const canonico = canonicalJson(objetoAcordado(base));
  return [{ etiqueta: "Acuerdo de la tarea", local: await sha256Hex(canonico), guardado: task.rules_hash,
    onchain: task.onchain?.rules_hash ?? null, canonico }];
}

type Resultado = { filas?: Fila[]; error?: string };

async function cargar(taskId: string): Promise<Resultado> {
  try {
    return { filas: await revisar(await api.task(taskId.trim())) };
  } catch (e) {
    return { error: e instanceof ApiError && e.status === 404 ? "No existe una tarea con ese identificador." : "No se pudo leer la tarea. Intenta de nuevo." };
  }
}

/** Cualquiera recalcula en su navegador el hash de los criterios y lo compara con el contrato. */
export default function VerificarPage({ searchParams }: { searchParams: Promise<{ tarea?: string }> }) {
  const { tarea } = use(searchParams);
  const [id, setId] = useState(tarea ?? "");
  const [filas, setFilas] = useState<Fila[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(Boolean(tarea));

  function aplicar(r: Resultado) {
    setFilas(r.filas ?? null); setError(r.error ?? null); setCargando(false);
  }

  function verificar(taskId: string) {
    if (!taskId.trim()) return;
    setCargando(true); setError(null); setFilas(null);
    void cargar(taskId).then(aplicar);
  }

  useEffect(() => {
    if (!tarea) return;
    let vigente = true;
    void cargar(tarea).then((r) => { if (vigente) aplicar(r); });
    return () => { vigente = false; };
  }, [tarea]);

  return (
    <div className="space-y-8">
      <div className="page-heading">
        <span className="justify-self-start rounded-full bg-secondary px-3 py-1 text-xs font-bold tracking-[0.06em] text-primary uppercase">Acuerdo verificable</span>
        <h1>Comprueba que los criterios no cambiaron</h1>
        <p className="max-w-2xl text-base text-muted-foreground">
          Tu navegador recalcula el SHA-256 de los criterios acordados y lo compara con el que quedó guardado en el contrato de Stellar al depositar. No depende de nuestro servidor para el cálculo.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={(e) => { e.preventDefault(); verificar(id); }}>
            <div className="flex-1 space-y-2">
              <Label htmlFor="tarea">Identificador de la tarea</Label>
              <Input id="tarea" value={id} onChange={(e) => setId(e.target.value)} placeholder="Por ejemplo, Fzw_5tOvZG-FmM7o" autoComplete="off" />
            </div>
            <Button type="submit" className="min-h-10" disabled={cargando || !id.trim()}>
              <ShieldCheck /> {cargando ? "Calculando…" : "Verificar"}
            </Button>
          </form>
          {error && <p className="mt-3 text-sm text-danger">{error}</p>}
        </CardContent>
      </Card>

      {filas?.map((f) => {
        const coincideGuardado = f.local === f.guardado;
        const coincideOnchain = f.onchain !== null && f.local === f.onchain;
        const ok = coincideGuardado && coincideOnchain;
        return (
          <Card key={f.etiqueta}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {ok ? <CheckCircle2 className="text-success-strong" /> : <XCircle className="text-danger" />}
                {f.etiqueta}
              </CardTitle>
              <CardDescription>
                {ok ? "El hash calculado aquí es el mismo que guarda el contrato: los criterios son exactamente los acordados."
                  : f.onchain === null ? "El contrato todavía no tiene un depósito para esta tarea, así que no hay hash on-chain con qué comparar."
                  : "El hash no coincide con el del contrato."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <dl className="grid gap-2">
                <div><dt className="text-muted-foreground">Calculado en tu navegador</dt><dd className="font-mono break-all">{f.local}</dd></div>
                <div><dt className="text-muted-foreground">En el contrato (on-chain)</dt><dd className="font-mono break-all">{f.onchain ?? "—"}</dd></div>
                <div><dt className="text-muted-foreground">Guardado por el backend</dt><dd className="font-mono break-all">{f.guardado}{coincideGuardado ? " ✓" : " ✗"}</dd></div>
              </dl>
              <details>
                <summary className="cursor-pointer text-muted-foreground">Ver el JSON canónico que se hashea</summary>
                <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap break-all">{f.canonico}</pre>
              </details>
            </CardContent>
          </Card>
        );
      })}

      <p className="text-sm text-muted-foreground">
        La definición del hash está en el <Link className="underline" href="https://github.com/rodyxdev/cumpleycobra#readme">README</Link>: JSON canónico con claves ordenadas, sin espacios, en UTF-8 y con los textos en NFC.
      </p>
    </div>
  );
}
