"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { UsdcGate } from "@/components/usdc-gate";
import { useWallet } from "@/hooks/use-wallet";
import { api, type CriterionReview, type Demo, type Spec } from "@/lib/api";
import { Money, FxNotice, parsePesos, useFx } from "@/components/money";
import { store } from "@/lib/store";

export function AssistedTaskForm() {
  const router = useRouter();
  const wallet = useWallet();
  const [demo, setDemo] = useState<Demo | null>(null);
  const [raw, setRaw] = useState("");
  const [original, setOriginal] = useState("");
  const [spec, setSpec] = useState<Spec | null>(null);
  const [reviews, setReviews] = useState<CriterionReview[] | null>(null);
  const [busy, setBusy] = useState<"draft" | "review" | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("20");
  const [minutes, setMinutes] = useState("10");

  useEffect(() => {
    let alive = true;
    api.demo().then((value) => {
      if (!alive) return;
      setDemo(value);
      setRaw((current) => current || value.raw_request);
    }, (e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, []);

  const fx = useFx();
  const units = fx ? parsePesos(amount, fx.rate) : null;
  const mins = /^\d+$/.test(minutes) ? Number(minutes) : NaN;
  const validCriteria = !!spec && spec.criteria.length > 0 && spec.criteria.length <= 8 &&
    spec.criteria.every((c) => c.trim().length > 0 && c.length <= 300);
  const valid = validCriteria && !!spec?.description.trim() && units !== null && mins > 0 && mins <= 43200;

  function editCriteria(criteria: string[]) {
    if (!spec) return;
    setSpec({ ...spec, criteria });
    setReviews(null); // una revisión solo corresponde a la lista que se envió
  }

  async function improve() {
    setBusy("draft");
    setError(null);
    try {
      const result = await api.draft(raw);
      setSpec(result);
      setOriginal(raw);
      setReviews(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  }

  async function review() {
    if (!spec) return;
    setBusy("review");
    setError(null);
    try { setReviews((await api.reviewDraft(spec.criteria)).criteria); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!spec || !valid || !wallet.address || units === null) return;
    setBusy("create");
    setError(null);
    try {
      const created = await api.createTask({
        ...spec, raw_request: original, client_address: wallet.address,
        amount: units, deadline_minutes: mins,
      });
      store.saveClientTask({ ...created, amount: units, deadline_minutes: mins, client_address: wallet.address });
      router.replace(`/cliente?tarea=${encodeURIComponent(created.task_id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6" aria-busy={!!busy}>
      <Card data-testid="pedido-paso-1">
        <CardHeader>
          <CardTitle>1. Tu pedido original</CardTitle>
          <CardDescription>Describe qué necesitas. La IA te ayudará a convertirlo en criterios que puedas revisar.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="pedido-original">¿Qué quieres que haga tu código?</Label>
          <Textarea id="pedido-original" value={raw} maxLength={2000} rows={4} disabled={!!busy}
            placeholder="Escribe aquí tu pedido…" onChange={(e) => setRaw(e.target.value)} />
          <p className="text-right text-xs text-muted-foreground">{raw.length}/2000 caracteres</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button className="h-auto min-h-9 whitespace-normal" onClick={improve} disabled={!!busy || !raw.trim() || raw.length > 2000}>
              {busy === "draft" ? "Preparando tu pedido…" : "Pídele a la IA que mejore tu pedido"}
            </Button>
            <Button variant="link" className="h-auto whitespace-normal" disabled={!demo || !!busy} onClick={() => {
              if (!demo) return;
              setRaw(demo.raw_request); setOriginal(demo.raw_request);
              setSpec(structuredClone(demo.spec)); setReviews(null); setError(null);
            }}>Usar la plantilla de la demo</Button>
          </div>
          {spec && <p className="text-xs text-muted-foreground">Generar otra versión o usar la plantilla reemplaza las ediciones de abajo.</p>}
        </CardContent>
      </Card>

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {spec && (
        <Card data-testid="pedido-paso-2">
          <CardHeader>
            <CardTitle>2. Revisa tu acuerdo verificable</CardTitle>
            <CardDescription>Edita la propuesta antes de crear la tarea. Tu programador aceptará esta versión final.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {raw !== original && <p className="text-sm text-amber-800">Cambiaste el pedido de arriba. Esta versión corresponde al original que se muestra aquí; vuelve a generar para usar el nuevo pedido.</p>}
            <div className="grid gap-5 md:grid-cols-[1fr_2fr]">
              <div className="space-y-2 rounded-lg bg-muted/60 p-4">
                <h3 className="text-sm font-medium">Tu pedido original</h3>
                <p className="whitespace-pre-wrap text-sm text-muted-foreground">{original}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="descripcion">Versión mejorada · descripción</Label>
                <Textarea id="descripcion" rows={5} value={spec.description} disabled={!!busy}
                  onChange={(e) => setSpec({ ...spec, description: e.target.value })} />
                <p className="text-xs text-muted-foreground">Python · {spec.allowed_deps.length ? `Librerías permitidas: ${spec.allowed_deps.join(", ")}` : "Sin librerías permitidas"}</p>
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">Criterios acordados ({spec.criteria.length}/8)</h3>
              {spec.criteria.map((criterion, index) => {
                const review = reviews?.[index];
                return <div key={index} className="space-y-2 rounded-lg border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Label htmlFor={`criterio-${index}`}>Criterio {index + 1}</Label>
                    <Button size="sm" variant="ghost" aria-label={`Quitar criterio ${index + 1}`} disabled={!!busy || spec.criteria.length === 1}
                      onClick={() => editCriteria(spec.criteria.filter((_, i) => i !== index))}>Quitar</Button>
                  </div>
                  <Textarea id={`criterio-${index}`} value={criterion} maxLength={300} rows={2} disabled={!!busy}
                    onChange={(e) => editCriteria(spec.criteria.map((c, i) => i === index ? e.target.value : c))} />
                  <p className="text-right text-xs text-muted-foreground">{criterion.length}/300</p>
                  {review && <div className={`text-sm ${review.vague ? "text-amber-800" : "text-emerald-700"}`}>
                    {review.vague ? <>
                      <p>Criterio vago · {review.suggestion}</p>
                      <Button className="mt-2" variant="outline" size="sm" disabled={!!busy}
                        onClick={() => editCriteria(spec.criteria.map((c, i) => i === index ? review.suggestion! : c))}>
                        Aplicar sugerencia
                      </Button>
                    </> : <p>✓ Verificable por lectura del código</p>}
                  </div>}
                </div>;
              })}
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" disabled={!!busy || spec.criteria.length >= 8} onClick={() => editCriteria([...spec.criteria, ""])}>Agregar criterio</Button>
                <Button variant="secondary" disabled={!!busy || !validCriteria} onClick={review}>
                  {busy === "review" ? "Revisando criterios…" : "Revisar criterios"}
                </Button>
              </div>
              {reviews && <p role="status" className="text-sm text-muted-foreground">Revisión completada. Las sugerencias solo se aplican si tú las eliges.</p>}
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">Ejemplos de entrada y salida</h3>
              {spec.examples.map((example, index) => <div key={index} className="space-y-2 rounded-lg border p-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  {(["input", "output"] as const).map((field) => <div key={field} className="space-y-2">
                    <Label htmlFor={`ejemplo-${index}-${field}`}>{field === "input" ? "Entrada" : "Salida"} {index + 1}</Label>
                    <Textarea id={`ejemplo-${index}-${field}`} value={example[field]} rows={2} disabled={!!busy}
                      onChange={(e) => setSpec({ ...spec, examples: spec.examples.map((x, i) => i === index ? { ...x, [field]: e.target.value } : x) })} />
                  </div>)}
                </div>
                <Button size="sm" variant="ghost" disabled={!!busy} aria-label={`Quitar ejemplo ${index + 1}`}
                  onClick={() => setSpec({ ...spec, examples: spec.examples.filter((_, i) => i !== index) })}>Quitar ejemplo</Button>
              </div>)}
              <Button variant="outline" disabled={!!busy} onClick={() => setSpec({ ...spec, examples: [...spec.examples, { input: "", output: "" }] })}>Agregar ejemplo</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {spec && <UsdcGate role="cliente">{() => (
        <Card>
          <CardHeader>
            <CardTitle>3. Crea la tarea</CardTitle>
            <CardDescription>Al crearla, los criterios quedan acordados. Después podrás invitar a tu programador y depositar con Pollar.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2"><Label htmlFor="monto">Monto estimado (MXN)</Label>
                <Input id="monto" value={amount} inputMode="decimal" disabled={!!busy} onChange={(e) => setAmount(e.target.value)} /></div>
              <div className="space-y-2"><Label htmlFor="plazo">Plazo (minutos)</Label>
                <Input id="plazo" value={minutes} inputMode="numeric" disabled={!!busy} onChange={(e) => setMinutes(e.target.value)} /></div>
            </div>
            {units !== null && <Money units={units} />}
            <FxNotice />
            {!valid && <p className="text-sm text-amber-800">Completa la descripción y los criterios, un monto válido y un plazo entre 1 y 43200 minutos.</p>}
            <Button disabled={!valid || !!busy} onClick={create}>{busy === "create" ? "Creando…" : "Crear tarea"}</Button>
          </CardContent>
        </Card>
      )}</UsdcGate>}
    </div>
  );
}
