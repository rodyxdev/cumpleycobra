import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <div className="space-y-10 py-8">
      <section className="space-y-4">
        <p className="text-sm font-medium text-muted-foreground">Acuerdo verificable para trabajo de código</p>
        <h1 className="text-4xl font-semibold tracking-tight">Si cumple lo acordado, cobras. Sin discusiones.</h1>
        <p className="max-w-2xl text-muted-foreground">
          El cliente fija criterios medibles y deposita USDC en un contrato Soroban. El programador acepta esos
          criterios y entrega su código. El Motor de Análisis Estático de Código basado en LLM lo evalúa contra lo
          acordado y, si cumple, el pago se libera en segundos.
        </p>
        <Button nativeButton={false} render={<Link href="/cliente" />}>
          Crear una tarea
        </Button>
      </section>
      <section className="grid gap-4 sm:grid-cols-3">
        {[
          ["1. Acuerdo", "El cliente publica la tarea con criterios verificables y comparte el enlace con su programador."],
          ["2. Depósito", "El monto queda en el contrato con el hash de los criterios; nadie puede cambiarlos después."],
          ["3. Veredicto", "El motor revisa el código contra cada criterio. Si cumple, el contrato paga al programador."],
        ].map(([title, text]) => (
          <div key={title} className="rounded-xl border bg-background p-4">
            <div className="font-medium">{title}</div>
            <p className="mt-1 text-sm text-muted-foreground">{text}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
