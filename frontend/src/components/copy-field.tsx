"use client";

import { Check, Copy, Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Campo con botón de copiar. Con `secret`, el token del enlace se oculta en pantalla
 * (para capturas y demos) pero se copia completo.
 */
export function CopyField({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [shown, setShown] = useState(!secret);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  const display = shown ? value : value.replace(/(invitacion=)[^&]+/, "$1••••••••••••");

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 rounded-md border bg-muted/40 px-3 py-2 font-mono text-xs break-all" data-value={value}>
          {display}
        </code>
        {secret && (
          <Button variant="ghost" size="sm" onClick={() => setShown(!shown)} aria-label={shown ? "Ocultar" : "Mostrar"}>
            {shown ? <EyeOff /> : <Eye />}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={copy} aria-label={`Copiar ${label}`}>
          {copied ? <Check /> : <Copy />}
          {copied ? "Copiado" : "Copiar"}
        </Button>
      </div>
    </div>
  );
}
