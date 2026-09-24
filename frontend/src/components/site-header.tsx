import Link from "next/link";

import { WalletConnect } from "@/components/wallet-connect";

export function SiteHeader() {
  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
        <Link href="/" className="font-semibold tracking-tight">
          Cumple<span className="text-muted-foreground">&amp;</span>Cobra
        </Link>
        <nav className="flex items-center gap-4 text-sm text-muted-foreground">
          <Link href="/cliente" className="hover:text-foreground">
            Soy cliente
          </Link>
          <span className="hidden sm:inline">Testnet de Stellar</span>
          <WalletConnect />
        </nav>
      </div>
    </header>
  );
}
