import Link from "next/link";
import { ArrowRight, Check, FileCheck2, LockKeyhole, Wallet } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <div className="space-y-16 pb-8 lg:space-y-24">
      <section className="grid items-center gap-12 py-5 lg:grid-cols-[1.35fr_1fr] lg:gap-16 lg:py-10">
        <div className="space-y-7">
          <p className="eyebrow flex items-center gap-3"><span className="h-px w-8 bg-primary" />Acuerdo verificable para trabajo de código</p>
          <h1 className="max-w-[750px] text-[clamp(2.75rem,5.5vw,4.75rem)] leading-[1.04] font-medium tracking-[-0.065em]">
            Si cumple lo acordado, <span className="text-primary">cobras.</span> <span className="mt-3 block">Sin discusiones.</span>
          </h1>
          <p className="max-w-xl text-lg leading-relaxed text-muted-foreground">
            Acuerden qué debe hacer el código. El cliente deposita, el programador entrega y el contrato paga cuando se cumple lo acordado.
          </p>
          <div className="space-y-4 pt-1">
            <Button size="lg" nativeButton={false} render={<Link href="/cliente" />}>
              Crear una tarea <ArrowRight aria-hidden="true" data-icon="inline-end" />
            </Button>
            <p className="text-sm text-muted-foreground">USDC en Stellar · Wallet con Pollar</p>
          </div>
        </div>
        <div className="relative rounded-2xl border border-border bg-card p-7 sm:p-9">
          <div className="mb-8 flex items-center justify-between border-b pb-5">
            <span className="eyebrow">Del acuerdo al pago</span>
            <FileCheck2 className="size-6 text-primary" strokeWidth={1.5} aria-hidden="true" />
          </div>
          <ol className="space-y-7">
            {[
              ["01", "Criterios claros", "Una versión final que ambos aceptan."],
              ["02", "Dinero en el contrato", "El depósito respalda el acuerdo."],
              ["03", "Una razón por criterio", "El código se revisa contra lo acordado."],
            ].map(([number, title, detail]) => <li key={number} className="flex items-start gap-4">
              <span className="pt-1 text-sm tabular-nums text-muted-foreground">{number}</span>
              <div className="space-y-1"><p className="text-lg font-medium tracking-tight">{title}</p><p className="text-base text-muted-foreground">{detail}</p></div>
            </li>)}
          </ol>
          <div className="mt-8 flex items-center gap-3 rounded-lg bg-secondary px-4 py-4 text-primary">
            <Check className="size-5 shrink-0" aria-hidden="true" /><p className="font-medium">Si cumple, el pago se libera.</p>
          </div>
        </div>
      </section>
      <section className="space-y-8 border-t pt-10" aria-label="Cómo funciona">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <h2 className="text-3xl font-medium tracking-[-0.045em] sm:text-4xl">Un acuerdo. Tres pasos.</h2>
          <p className="max-w-sm text-base text-muted-foreground">Del pedido al cobro, con los mismos criterios de principio a fin.</p>
        </div>
        <div className="grid gap-8 md:grid-cols-3 md:gap-0">
          {[
            { n: "01", title: "Acuerdo", text: "El cliente publica la tarea con criterios verificables y comparte el enlace con su programador.", Icon: FileCheck2 },
            { n: "02", title: "Depósito", text: "El monto queda en el contrato con el hash de los criterios; nadie puede cambiarlos después.", Icon: LockKeyhole },
            { n: "03", title: "Veredicto", text: "El motor revisa el código contra cada criterio. Si cumple, el contrato paga al programador.", Icon: Wallet },
          ].map(({ n, title, text, Icon }) => (
            <article key={n} className="space-y-4 border-t pt-6 md:border-t-0 md:border-l md:px-8 md:pt-0 md:first:border-l-0 md:first:pl-0 md:last:pr-0">
              <div className="flex items-center justify-between text-muted-foreground"><span className="text-sm tabular-nums">{n}</span><Icon className="size-5" strokeWidth={1.5} aria-hidden="true" /></div>
              <h3 className="text-xl font-semibold tracking-tight">{title}</h3>
              <p className="text-base leading-relaxed text-muted-foreground">{text}</p>
            </article>
          ))}
        </div>
      </section>
      <p className="max-w-3xl text-base leading-relaxed text-muted-foreground">El Motor de Análisis Estático de Código basado en LLM evalúa el código contra los criterios acordados. El depósito y el pago quedan registrados en el contrato Soroban.</p>
    </div>
  );
}
