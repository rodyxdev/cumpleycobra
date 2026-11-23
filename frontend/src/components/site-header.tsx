import Image from "next/image";
import Link from "next/link";

import { HeaderInbox } from "@/components/header-inbox";
import { HeaderIdentity } from "@/components/identity";
import { WalletConnect } from "@/components/wallet-connect";

export function SiteHeader() {
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex min-h-20 max-w-[1248px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-3 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5" aria-label="Cumple&Cobra, inicio">
          <Image src="/brand/logo-mark.png" alt="" width={40} height={36} priority />
          <span className="brand-heading text-xl text-primary sm:text-[1.4rem]">
            Cumple<span className="text-success-strong">&amp;</span>Cobra
          </span>
        </Link>
        <nav className="flex flex-wrap items-center gap-2 text-base sm:gap-3">
          <Link href="/probar" className="rounded-lg bg-success-soft px-3 py-2 font-bold text-success-strong transition-colors hover:bg-secondary hover:text-primary">
            Pruébalo
          </Link>
          <Link href="/cliente" className="rounded-lg px-3 py-2 font-medium text-[#2E3A4D] transition-colors hover:bg-secondary hover:text-primary">
            Soy cliente
          </Link>
          <Link href="/programadores" className="rounded-lg px-3 py-2 font-medium text-[#2E3A4D] transition-colors hover:bg-secondary hover:text-primary">
            Programadores
          </Link>
          <span className="hidden rounded-full bg-secondary px-3 py-1 text-sm font-medium text-primary lg:inline">Testnet de Stellar</span>
          <HeaderInbox />
          <HeaderIdentity />
          <WalletConnect />
        </nav>
      </div>
    </header>
  );
}
