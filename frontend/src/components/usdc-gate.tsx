"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useWallet } from "@/hooks/use-wallet";
import { formatUsdc } from "@/lib/format";
import { usdcStatus, type UsdcStatus } from "@/lib/soroban";

/**
 * Bloqueo de wallet: primero conectar, luego una cuenta clásica (G…) y la trustline de USDC.
 * Hasta que todo eso existe, no se muestra nada más de la vista.
 */
export function UsdcGate({ role, children }: { role: "cliente" | "programador"; children: (u: UsdcStatus) => React.ReactNode }) {
  const wallet = useWallet();
  const [status, setStatus] = useState<UsdcStatus | null>(null);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    if (!wallet.address || !wallet.supported) return;
    try {
      setStatus(await usdcStatus(wallet.address));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [wallet.address, wallet.supported]);

  useEffect(() => {
    const first = setTimeout(check, 0);
    const id = setInterval(check, 8000); // el saldo cambia con depósitos y pagos
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [check]);

  if (!wallet.address) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Conecta tu wallet</CardTitle>
          <CardDescription>
            {role === "cliente"
              ? "Con ella depositas el monto de la tarea y apruebas pagos manualmente."
              : "El pago del contrato va a la dirección de esta wallet."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={wallet.connect}>{wallet.mode === "pollar" ? "Iniciar sesión con Pollar" : "Conectar Freighter"}</Button>
        </CardContent>
      </Card>
    );
  }

  if (!wallet.supported) {
    return (
      <Card>
        <CardContent className="text-sm">
          Esta wallet ({wallet.custody}) no es una cuenta clásica de Stellar (G…). Para Cumple&amp;Cobra usa una cuenta
          de Pollar con Google o correo.
        </CardContent>
      </Card>
    );
  }

  if (!status) return <p className="text-sm text-muted-foreground">Revisando tu cuenta en la red…</p>;

  if (!status.exists || !status.trustline) {
    return (
      <Card className="border-amber-300" data-testid="activar-usdc">
        <CardHeader>
          <CardTitle>Activar USDC</CardTitle>
          <CardDescription>
            {status.exists
              ? "Tu cuenta todavía no puede recibir USDC. Activa la trustline antes de continuar."
              : "Tu cuenta todavía no existe en la red de Stellar. Pollar la crea al activar USDC; si no, fondéala primero."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button
            disabled={activating}
            onClick={async () => {
              setActivating(true);
              setError(null);
              try {
                await wallet.activateUsdc();
                await check();
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e));
              } finally {
                setActivating(false);
              }
            }}
          >
            {activating ? "Activando…" : "Activar USDC"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <div className="text-xs text-muted-foreground" data-testid="saldo-usdc">
        Wallet {wallet.address.slice(0, 6)}…{wallet.address.slice(-4)} · saldo {formatUsdc(status.units)}
      </div>
      {children(status)}
    </>
  );
}
