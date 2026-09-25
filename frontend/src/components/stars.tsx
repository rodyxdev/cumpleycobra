"use client";

import { Star } from "lucide-react";

/** Calificación de solo lectura. */
export function Stars({ value, size = "size-5" }: { value: number; size?: string }) {
  const full = Math.round(value);
  return (
    <span className="inline-flex items-center gap-0.5" role="img" aria-label={`${value} de 5 estrellas`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} className={`${size} ${n <= full ? "fill-primary text-primary" : "text-border"}`} aria-hidden="true" />
      ))}
    </span>
  );
}

/** Selector de 1 a 5 estrellas (grupo de opciones accesible). */
export function StarPicker({ value, onChange, disabled }: { value: number; onChange: (n: number) => void; disabled?: boolean }) {
  return (
    <div className="flex items-center gap-1" role="radiogroup" aria-label="Calificación">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} de 5 estrellas`}
          data-testid={`estrella-${n}`} disabled={disabled} onClick={() => onChange(n)}
          className="rounded-md p-1 transition-colors hover:bg-secondary disabled:opacity-50">
          <Star className={`size-7 ${n <= value ? "fill-primary text-primary" : "text-muted-foreground"}`} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
