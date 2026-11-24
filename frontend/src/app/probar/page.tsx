"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UsdcGate } from "@/components/usdc-gate";
import { useWallet } from "@/hooks/use-wallet";
import { api, ApiError } from "@/lib/api";

const PASOS = [
  { titulo: "Entra con tu correo", texto: "Se crea tu wallet de Stellar. No instalas nada ni necesitas criptomonedas." },
  { titulo: "Recibe una tarea real", texto: "Un cliente ya acordó los criterios y depositó 1 USDC de prueba en el contrato." },
  { titulo: "Entrega el código", texto: "Corre en un contenedor aislado contra pruebas ocultas. Prueba el caso C (intenta engañar a la IA) y el caso A (correcto)." },
  { titulo: "Cobra en segundos", texto: "Si cumple lo acordado, el contrato te paga y ves la transacción en Stellar." },
];

/** «Pruébalo»: el visitante recibe una tarea ya depositada y entra como programador. */
export default function ProbarPage() {
  return (
    <div className="space-y-8">
      <div className="page-heading">
        <span className="justify-self-start rounded-full bg-secondary px-3 py-1 text-xs font-bold tracking-[0.06em] text-primary uppercase">Pruébalo · 3 minutos</span>
        <h1>Cobra por un código que cumple</h1>
        <p className="max-w-2xl text-base text-muted-foreground">
          Haces de programador en una tarea real de la testnet de Stellar. Nada usa dinero real.
        </p>
      </div>

      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PASOS.map((p, i) => (
          <li key={p.titulo} className="surface flex flex-col gap-2 p-5">
            <span className="brand-heading flex size-10 items-center justify-center rounded-[0.8rem] bg-secondary text-primary">{i + 1}</span>
            <h2 className="text-lg font-bold">{p.titulo}</h2>
            <p className="text-sm leading-relaxed text-muted-foreground">{p.texto}</p>
          </li>
        ))}
      </ol>

      <UsdcGate role="programador">{() => <TrialCard />}</UsdcGate>

      <p className="text-sm text-muted-foreground">
        ¿Prefieres ver el otro lado? En <Link href="/cliente" className="font-medium underline underline-offset-4">Soy cliente</Link>{" "}
        escribes un pedido y la IA lo convierte en criterios medibles (para depositar necesitas USDC de prueba).
      </p>
    </div>
  );
}

function TrialCard() {
  const wallet = useWallet();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    if (!wallet.address) return;
    setBusy(true);
    setError(null);
    try {
      const trial = await api.trial(wallet.address);
      router.push(trial.invite_path);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Card data-testid="probar">
      <CardHeader>
        <CardTitle>Tu tarea de prueba</CardTitle>
        <CardDescription>
          Te llevamos a una tarea depositada que nadie ha tomado. Acepta los criterios, envía el caso C y después el caso A.
          La primera verificación puede tardar 1 o 2 minutos más si el verificador se está encendiendo.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button size="lg" disabled={busy} onClick={start}>
          {busy ? "Buscando una tarea…" : <>Darme una tarea de prueba <ArrowRight className="size-4" aria-hidden="true" /></>}
        </Button>
        {error && <p role="alert" className="text-sm text-[var(--alert-foreground)]">{error}</p>}
      </CardContent>
    </Card>
  );
}
