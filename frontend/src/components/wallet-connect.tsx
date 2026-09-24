"use client";

import { WalletButton } from "@pollar/react";

import { Button } from "@/components/ui/button";
import { pollarEnabled, useWallet } from "@/hooks/use-wallet";
import { WALLET_MODE } from "@/lib/config";

/** Botón del encabezado: WalletButton de Pollar o, en el respaldo, "Conectar Freighter". */
export function WalletConnect() {
  if (pollarEnabled && WALLET_MODE === "pollar") return <WalletButton />;
  return <FreighterButton />;
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
