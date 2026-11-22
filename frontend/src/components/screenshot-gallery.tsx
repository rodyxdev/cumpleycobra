"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_URL, type Screenshot } from "@/lib/api";

const VIEWPORT_LABEL: Record<string, string> = { desktop: "1440 px", mobile: "390 px" };

/** Capturas de una entrega web (fase 3). Los enlaces vencen a los 15 minutos: recargar la página los renueva. */
export function ScreenshotGallery({ shots }: { shots: Screenshot[] }) {
  const visible = shots.filter((s) => s.url);
  if (visible.length === 0) return null;
  return (
    <Card data-testid="capturas">
      <CardHeader>
        <CardTitle>Capturas del navegador</CardTitle>
        <CardDescription>
          Las tomó el verificador, no la entrega. Los enlaces vencen a los 15 minutos; recarga para verlas de nuevo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-4 sm:grid-cols-2">
          {visible.map((s) => (
            <li key={s.id} className="min-w-0 space-y-2">
              <a href={`${API_URL}${s.url}`} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border">
                {/* eslint-disable-next-line @next/next/no-img-element -- imagen privada de la API con URL firmada */}
                <img src={`${API_URL}${s.url}`} alt={`Captura ${s.id}: ${s.page} a ${VIEWPORT_LABEL[s.viewport] ?? s.viewport}`}
                  className="max-h-96 w-full object-cover object-top" loading="lazy" />
              </a>
              <p className="text-xs text-muted-foreground">
                <span className="font-mono">{s.id}</span> · {s.page} · {VIEWPORT_LABEL[s.viewport] ?? s.viewport} · {s.label}
              </p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
