import Link from "next/link";

import { HeaderInbox } from "@/components/header-inbox";
import { HeaderIdentity } from "@/components/identity";
import { WalletConnect } from "@/components/wallet-connect";

export function SiteHeader() {
  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex min-h-20 max-w-[1248px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-8">
        <Link href="/" className="text-xl font-semibold tracking-[-0.06em] sm:text-2xl">
          Cumple<span className="text-primary">&amp;</span>Cobra
        </Link>
        <nav className="flex flex-wrap items-center gap-4 text-base text-muted-foreground sm:gap-6">
          <Link href="/cliente" className="transition-colors hover:text-primary">
            Soy cliente
          </Link>
          <Link href="/programadores" className="transition-colors hover:text-primary">
            Programadores
          </Link>
          <span className="hidden border-l pl-6 text-sm lg:inline">Testnet de Stellar</span>
          <HeaderInbox />
          <HeaderIdentity />
          <WalletConnect />
        </nav>
      </div>
    </header>
  );
}
