"use client";

import { WalletButton } from "@pollar/react";

import { Button } from "@/components/ui/button";
import { pollarEnabled, useWallet } from "@/hooks/use-wallet";
import { WALLET_MODE } from "@/lib/config";

/**
 * Botón del encabezado. Sin sesión: «Iniciar sesión» propio (el WalletButton de Pollar trae el texto
 * fijo «Login with Pollar»), que abre el mismo inicio de sesión de Pollar. Con sesión: el WalletButton
 * de Pollar (dirección, saldo y cerrar sesión). En el respaldo, "Conectar Freighter".
 */
export function WalletConnect() {
  if (pollarEnabled && WALLET_MODE === "pollar") return <PollarButton />;
  return <FreighterButton />;
}

function PollarButton() {
  const wallet = useWallet();
  if (wallet.address) return <WalletButton />;
  return (
    <Button size="sm" onClick={wallet.connect} data-testid="iniciar-sesion">
      Iniciar sesión
    </Button>
  );
}

function FreighterButton() {
  const wallet = useWallet();
  if (wallet.address) {
    return (
      <span className="rounded-md border px-2 py-1 font-mono text-xs" title={wallet.address}>
        Freighter · {wallet.address.slice(0, 4)}…{wallet.address.slice(-4)}
      </span>
    );
  }
  return (
    <Button size="sm" variant="outline" onClick={wallet.connect}>
      Conectar Freighter
    </Button>
  );
}
