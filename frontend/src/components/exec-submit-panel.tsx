"use client";

import { useEffect, useState } from "react";

import { ScreenshotGallery } from "@/components/screenshot-gallery";
import { SubmissionResult } from "@/components/submission-result";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useVerification } from "@/hooks/use-verification";
import { api, type Caso, type TaskView, type VerificationSource } from "@/lib/api";
import type { FreelancerTask } from "@/lib/store";
import { parseRepo, zipSource } from "@/lib/verification";

const MIN_SECONDS = 300; // mismo margen que el backend para encolar (VERIFY_MIN_SECONDS)

type Mode = "caso" | "pegar" | "zip" | "repo";

/** Entrega para una tarea que se verifica ejecutando el código (fase 3). */
export function ExecSubmitPanel({ task, mine, secondsLeft, onDone }: {
  task: TaskView; mine: FreelancerTask; secondsLeft: number | null; onDone: () => void;
}) {
  const [casos, setCasos] = useState<Caso[]>([]);
  const [mode, setMode] = useState<Mode>(task.web ? "zip" : "caso");
  const [selected, setSelected] = useState("A");
  const [pasted, setPasted] = useState("");
  const [zip, setZip] = useState<File | null>(null);
  const [repo, setRepo] = useState("");
  const [sha, setSha] = useState("");
  const [video, setVideo] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const { lines, busy, now, verdict, start } = useVerification();

  useEffect(() => {
    api.demo().then((d) => setCasos(d.casos), () => undefined);
  }, []);

  const web = !!task.web;
  const moduleName = task.interface?.symbols[0]?.module ?? "solucion";
  const caso = casos.find((c) => c.id === selected);
  const funded = task.onchain?.status === "Funded";
  const enoughTime = secondsLeft !== null && secondsLeft >= MIN_SECONDS;
  const blocked = !funded
    ? task.onchain ? "La tarea ya no está depositada." : "El cliente todavía no deposita el monto."
    : !enoughTime ? `Quedan menos de ${MIN_SECONDS / 60} minutos de plazo: ya no se puede verificar ejecutando.` : null;
  const ready = mode === "caso" ? !!caso : mode === "pegar" ? !!pasted.trim() : mode === "zip" ? !!zip : !!repo.trim();

  async function send() {
    setProblem(null);
    let source: VerificationSource;
    let label: string;
    if (mode === "caso" || mode === "pegar") {
      source = { kind: "code", code: mode === "caso" ? caso!.codigo : pasted };
      label = mode === "caso" ? caso!.nombre : "código pegado";
    } else if (mode === "zip") {
      const built = await zipSource(zip!);
      if (typeof built === "string") return setProblem(built);
      source = built;
      label = `ZIP ${zip!.name}`;
    } else {
      const parsed = parseRepo(repo, sha);
      if (typeof parsed === "string") return setProblem(parsed);
      source = { kind: "github_public", ...parsed };
      label = `${parsed.repo}@${parsed.sha.slice(0, 7)}`;
    }
    await start(task.task_id, mine.freelancer_address, mine.freelancer_token, label, source, video.trim() || null);
    onDone();
  }

  const modes: [Mode, string][] = web
    ? [["zip", "Subir ZIP"], ["repo", "Repositorio público"]]
    : [["caso", "Casos de la demo"], ["pegar", "Pegar código"], ["zip", "Subir ZIP"], ["repo", "Repositorio público"]];

  return (
    <div className="contents">
      <SubmissionResult lines={lines} now={now} busy={busy} amount={task.onchain?.amount} verdict={verdict} />
      {!busy && verdict?.verification?.screenshots?.length ? (
        <div className="order-2 min-w-0"><ScreenshotGallery shots={verdict.verification.screenshots} /></div>
      ) : null}
      <Card className="order-3 min-w-0">
        <CardHeader>
          <CardTitle>Entregar para verificar ejecutando</CardTitle>
          <CardDescription>
            {web ? (
              <>Tu sitio se sirve en un contenedor aislado, sin internet, y se revisa en un navegador real las páginas{" "}
                <code className="font-mono">{task.web!.pages.join(", ")}</code>. Entrega un index.html en la raíz o un
                proyecto npm con package-lock.json y un script build.</>
            ) : (
              <>Tu entrega corre en un contenedor aislado, sin red, contra la suite oculta. Debe exponer{" "}
                <code className="font-mono">{task.interface?.symbols.map((s) => `${s.module}.${s.name}`).join(", ")}</code>.</>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Cómo entregar">
            {modes.map(([m, text]) => (
              <Button key={m} role="tab" aria-selected={mode === m} variant={mode === m ? "default" : "outline"} size="sm"
                disabled={busy} onClick={() => setMode(m)}>{text}</Button>
            ))}
          </div>
          {mode === "caso" && (
            <>
              <div className="flex flex-wrap gap-2">
                {casos.map((c) => (
                  <Button key={c.id} size="sm" variant={selected === c.id ? "secondary" : "ghost"} disabled={busy}
                    onClick={() => setSelected(c.id)}>{c.nombre}</Button>
                ))}
              </div>
              <pre className="max-h-72 overflow-auto rounded-lg border bg-muted/40 p-5 font-mono text-sm">{caso?.codigo}</pre>
              <p className="text-xs text-muted-foreground">Se entrega como <code className="font-mono">{moduleName}.py</code>.</p>
            </>
          )}
          {mode === "pegar" && (
            <div className="space-y-2">
              <Label htmlFor="codigo-pegado">Contenido de {moduleName}.py</Label>
              <Textarea id="codigo-pegado" value={pasted} onChange={(e) => setPasted(e.target.value)} rows={10}
                className="font-mono text-sm" disabled={busy} placeholder="Pega aquí tu módulo de Python" />
            </div>
          )}
          {mode === "zip" && (
            <div className="space-y-2">
              <Label htmlFor="zip">ZIP del proyecto (máximo 2 MB)</Label>
              <Input id="zip" type="file" accept=".zip,application/zip" disabled={busy}
                onChange={(e) => setZip(e.target.files?.[0] ?? null)} />
              <p className="text-xs text-muted-foreground">{web
                ? "Sin node_modules: las dependencias permitidas se instalan con npm ci desde tu package-lock.json."
                : "Si usas dependencias, decláralas en requirements.txt; solo se instalan las permitidas."}</p>
            </div>
          )}
          {mode === "repo" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="repo">Repositorio público de GitHub</Label>
                <Input id="repo" value={repo} disabled={busy} onChange={(e) => setRepo(e.target.value)} placeholder="owner/nombre" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="sha">SHA del commit</Label>
                <Input id="sha" value={sha} disabled={busy} onChange={(e) => setSha(e.target.value)} className="font-mono" placeholder="40 caracteres" />
              </div>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="video-demo-exec">Enlace de Google Drive al video demo (opcional)</Label>
            <Input id="video-demo-exec" type="url" maxLength={1000} value={video} disabled={busy}
              onChange={(e) => setVideo(e.target.value)} placeholder="https://drive.google.com/file/d/…/view" />
            <p className="text-xs text-muted-foreground">Compártelo como &apos;cualquier persona con el enlace&apos; y que dure máximo 3 minutos.</p>
          </div>
          {problem && <p role="alert" className="text-sm text-[var(--alert-foreground)]">{problem}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="success" size="lg" onClick={send} disabled={busy || !!blocked || !ready} data-testid="verificar">
              {busy ? "Verificando…" : "Enviar al verificador"}
            </Button>
            {blocked && <span className="text-sm text-muted-foreground">{blocked}</span>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
