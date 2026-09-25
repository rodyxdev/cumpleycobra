"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { StarPicker, Stars } from "@/components/stars";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Rating } from "@/lib/api";
import { MAX_COMMENT, ratingProblem } from "@/lib/reputation";

/** El cliente califica una vez, con la tarea Pagada en el contrato. La calificación es pública. */
export function RatingCard({ taskId, clientToken, freelancer, rating, onRated }: {
  taskId: string;
  clientToken: string;
  freelancer: string | null;
  rating: Rating | null | undefined;
  onRated: () => void;
}) {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Rating | null>(null);
  const done = saved ?? rating ?? null;
  const problem = stars ? ratingProblem(stars, comment) : null;

  async function send() {
    setSending(true);
    setError(null);
    try {
      const r = await api.rateTask(taskId, clientToken, stars, comment.trim() || null);
      setSaved({ estrellas: r.estrellas, comentario: r.comentario });
      onRated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  const profile = freelancer && (
    <Link href={`/programador/${freelancer}`} data-testid="perfil-programador"
      className="inline-flex items-center gap-2 text-base font-medium text-primary underline-offset-4 hover:underline">
      Ver perfil del programador <ArrowRight className="size-4" aria-hidden="true" />
    </Link>
  );

  return (
    <Card data-testid="calificar">
      <CardHeader>
        <CardTitle>Califica a tu programador</CardTitle>
        <CardDescription>
          {done
            ? "Tu calificación ya forma parte del historial verificable del programador."
            : "Una sola vez por tarea. Tu calificación aparece en el perfil público del programador, junto al pago en Stellar."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {done ? (
          <div className="space-y-2" role="status">
            <div className="flex items-center gap-3">
              <Stars value={done.estrellas} />
              <span className="text-base">Calificaste con {done.estrellas} de 5 estrellas.</span>
            </div>
            {done.comentario && <p className="text-base text-muted-foreground">«{done.comentario}»</p>}
          </div>
        ) : (
          <>
            <StarPicker value={stars} onChange={setStars} disabled={sending} />
            <div className="space-y-2">
              <Label htmlFor="comentario">Comentario (opcional)</Label>
              <Textarea id="comentario" rows={3} maxLength={MAX_COMMENT} value={comment} disabled={sending}
                placeholder="¿Cómo fue trabajar con tu programador?" onChange={(e) => setComment(e.target.value)} />
              <p className="text-right text-xs text-muted-foreground">{comment.length}/{MAX_COMMENT}</p>
            </div>
            {problem && <p className="text-sm text-[var(--alert-foreground)]">{problem}</p>}
            {error && <p role="alert" className="text-sm text-[var(--alert-foreground)]">{error}</p>}
            <Button data-testid="enviar-calificacion" disabled={!stars || !!problem || sending} onClick={send}>
              {sending ? "Enviando…" : "Enviar calificación"}
            </Button>
          </>
        )}
        {profile}
      </CardContent>
    </Card>
  );
}
