"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export function VideoDemo({ url }: { url?: string | null }) {
  const [open, setOpen] = useState(false);
  // Solo se incrustan URLs canónicas validadas por el backend, nunca HTML del usuario.
  if (!url || !/^https:\/\/drive\.google\.com\/file\/d\/[A-Za-z0-9_-]{10,200}\/preview$/.test(url)) return null;
  return <div className="space-y-2">
    <Button variant="outline" size="sm" onClick={() => setOpen(!open)}>{open ? "Ocultar video demo" : "Ver video demo"}</Button>
    {open && <iframe title="Video demo de la entrega" src={url} className="aspect-video w-full rounded-lg border" allow="fullscreen" allowFullScreen referrerPolicy="no-referrer" />}
    <p className="text-xs text-muted-foreground">Evidencia de apoyo. Si no se reproduce, revisa los permisos del enlace con el programador.</p>
  </div>;
}
