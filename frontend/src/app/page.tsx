import Link from "next/link";
import { ArrowRight, ArrowUpRight, Check } from "lucide-react";

import { explorerTx } from "@/lib/format";

// Ejemplo real: la tarea de la demo pagada en testnet el 20 de noviembre de 2026.
const EJEMPLO_TX = "e5284043bdfde33173e64608cd15bbff6ea9a0ae50097763508254e9dc19db48";
const EJEMPLO_CRITERIOS = [
  "Firma de la función",
  "Fórmula del descuento",
  "Redondeo a 2 decimales",
  "Orden y lista vacía",
  "Sin dependencias externas",
  "Termina con cualquier lista",
];

const PASOS = [
  { n: "01", quien: "Cliente", titulo: "Acuerdo", texto: "Describe lo que necesita y la IA lo convierte en criterios medibles que él edita." },
  { n: "02", quien: "Cliente", titulo: "Depósito", texto: "El USDC queda en el contrato junto con el hash de los criterios." },
  { n: "03", quien: "Programador", titulo: "Entrega", texto: "Acepta los criterios, entrega su código y un video demo de su trabajo." },
  { n: "04", quien: "Contrato", titulo: "Veredicto y pago", texto: "Si cumple cada criterio, el contrato le paga en segundos." },
];

const PRUEBAS = [
  { que: "Criterios", titulo: "rules_hash en el contrato", valor: "391136734bc9…c4f79c96" },
  { que: "Código", titulo: "code_hash de la entrega", valor: "c9b846f4cafc…2334e534" },
  { que: "Veredicto", titulo: "verdict_hash en el evento", valor: "publicado con el pago" },
  { que: "Pago", titulo: "Transacción en Stellar", valor: "e5284043bdfd…9dc19db48" },
];

export default function Home() {
  return (
    <div className="space-y-20 pb-6 lg:space-y-24">
      <section className="overflow-hidden rounded-[1.75rem] bg-primary px-6 py-12 text-white sm:px-10 sm:py-14 lg:px-14 lg:py-16">
        <div className="grid grid-cols-[minmax(0,1fr)] items-center gap-12 lg:grid-cols-[1.25fr_1fr] lg:gap-14">
          <div className="min-w-0 space-y-7">
            <p className="flex items-center gap-3 text-sm font-bold tracking-[0.12em] text-[#D5E1EF] uppercase">
              <span className="h-0.5 w-7 bg-[var(--hero-accent)]" aria-hidden="true" />Pago verificado para código
            </p>
            <h1 className="brand-heading text-[clamp(2.5rem,5.2vw,4.25rem)] leading-[1.04]">
              Si cumple lo acordado, <span className="text-[var(--hero-accent)]">cobras.</span>
              <span className="block">Sin discusiones.</span>
            </h1>
            <p className="max-w-xl text-lg leading-relaxed text-[#D5E1EF] sm:text-[1.2rem]">
              El cliente y el programador acuerdan criterios medibles. El dinero espera en un contrato de Stellar y se
              libera solo cuando el motor confirma que el código cumple.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Link href="/probar" className="inline-flex h-13 items-center gap-2.5 rounded-xl bg-[var(--success)] px-6 text-[1.05rem] font-bold text-white transition-colors hover:bg-[var(--success-strong)]">
                Pruébalo en 3 minutos <ArrowRight className="size-5" aria-hidden="true" />
              </Link>
              <Link href="/cliente" className="inline-flex h-13 items-center rounded-xl border-[1.5px] border-white/45 px-6 text-[1.05rem] font-semibold text-white transition-colors hover:bg-white/10">
                Crear una tarea
              </Link>
              <Link href="/programadores" className="inline-flex h-13 items-center rounded-xl border-[1.5px] border-white/45 px-6 text-[1.05rem] font-semibold text-white transition-colors hover:bg-white/10">
                Ver programadores
              </Link>
            </div>
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-[#D5E1EF]">
              <span>USDC en Stellar</span><span aria-hidden="true">·</span>
              <span>Entras con tu correo, sin extensiones</span><span aria-hidden="true">·</span>
              <span>Contrato Soroban público</span>
            </p>
          </div>

          <figure className="w-full min-w-0 max-w-[30rem] justify-self-center space-y-5 rounded-[1.4rem] bg-card p-5 text-foreground shadow-[0_24px_60px_rgba(8,30,60,0.32)] sm:p-7 lg:justify-self-end">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1">
                <p className="text-xs font-bold tracking-[0.1em] text-muted-foreground uppercase">Veredicto</p>
                <p className="font-mono text-[0.95rem]">aplicar_descuento()</p>
              </div>
              <span className="inline-flex items-center gap-2 rounded-full bg-success-soft px-3.5 py-1.5 text-sm font-bold text-success-strong">
                <Check className="size-4" strokeWidth={3} aria-hidden="true" />Cumple
              </span>
            </div>
            <ul className="space-y-2.5">
              {EJEMPLO_CRITERIOS.map((c) => (
                <li key={c} className="flex items-center gap-3 text-[0.95rem]">
                  <span className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-success text-white">
                    <Check className="size-3.5" strokeWidth={3.5} aria-hidden="true" />
                  </span>
                  {c}
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-end justify-between gap-4 border-t border-dashed border-[#C9D2DC] pt-4">
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Pagado al programador</p>
                <p className="brand-heading text-4xl text-primary">1.00 <span className="text-xl">USDC</span></p>
              </div>
              <a href={explorerTx(EJEMPLO_TX)} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1.5 font-mono text-sm text-primary hover:underline">
                tx e528…db48 <ArrowUpRight className="size-4" aria-hidden="true" />
              </a>
            </div>
            <figcaption className="text-xs text-muted-foreground">Pago real en la testnet de Stellar.</figcaption>
          </figure>
        </div>
      </section>

      <section className="space-y-10" aria-labelledby="como">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h2 id="como" className="brand-heading text-3xl text-primary sm:text-[2.5rem]">Del acuerdo al pago</h2>
          <p className="max-w-md text-base leading-relaxed text-muted-foreground">Los mismos criterios de principio a fin: nadie puede cambiarlos después del depósito.</p>
        </div>
        <ol className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {PASOS.map((p) => (
            <li key={p.n} className="surface flex flex-col gap-3.5 p-6">
              <div className="flex items-center justify-between">
                <span className="brand-heading flex size-12 items-center justify-center rounded-[0.9rem] bg-secondary text-lg text-primary">{p.n}</span>
                <span className="text-xs font-bold tracking-[0.06em] text-success-strong uppercase">{p.quien}</span>
              </div>
              <h3 className="text-xl font-bold tracking-tight">{p.titulo}</h3>
              <p className="text-base leading-relaxed text-muted-foreground">{p.texto}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid items-start gap-10 lg:grid-cols-[1fr_2fr]" aria-labelledby="prueba">
        <div className="space-y-4">
          <h2 id="prueba" className="brand-heading text-3xl text-primary sm:text-[2.5rem]">Todo queda como prueba</h2>
          <p className="text-base leading-relaxed text-muted-foreground sm:text-lg">
            Cada paso deja una huella que cualquiera puede recalcular: los criterios, el código entregado, el veredicto y
            el pago. El contrato es la fuente de verdad del dinero.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {PRUEBAS.map((h) => (
            <div key={h.que} className="surface flex flex-col gap-2.5 p-5">
              <span className="text-xs font-bold tracking-[0.08em] text-muted-foreground uppercase">{h.que}</span>
              <span className="text-lg font-bold">{h.titulo}</span>
              <code className="rounded-lg bg-secondary px-2.5 py-2 font-mono text-[0.8rem] break-all text-primary">{h.valor}</code>
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-8 rounded-[1.5rem] bg-primary px-6 py-10 text-white sm:px-11" aria-labelledby="sigue">
        <div className="max-w-2xl space-y-3">
          <span className="inline-block rounded-full bg-white/15 px-3 py-1 text-xs font-bold tracking-[0.08em] uppercase">Nuevo · beta</span>
          <h2 id="sigue" className="brand-heading text-3xl">Verificación por ejecución</h2>
          <p className="text-base leading-relaxed text-[#D5E1EF] sm:text-lg">
            Al crear la tarea, elige «Verificar ejecutando»: el código corre en un contenedor aislado contra pruebas
            ocultas, y un sitio web se revisa en un navegador real, con capturas como evidencia. Si una prueba falla, no
            se paga.
          </p>
        </div>
        <Link href="/probar" className="inline-flex h-13 items-center rounded-xl bg-white px-6 text-[1.05rem] font-bold text-primary transition-colors hover:bg-secondary">
          Pruébalo en 3 minutos
        </Link>
      </section>

      <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
        El código se verifica ejecutándolo en un contenedor aislado contra pruebas ocultas (beta) o leyéndolo con el
        Motor de Análisis Estático de Código basado en LLM. El depósito y el pago quedan registrados en el contrato
        Soroban.
      </p>
    </div>
  );
}
