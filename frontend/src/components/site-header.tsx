import Image from "next/image";
import Link from "next/link";

import { HeaderInbox } from "@/components/header-inbox";
import { HeaderIdentity } from "@/components/identity";
import { WalletConnect } from "@/components/wallet-connect";

const NAV_LINK =
  "inline-flex min-h-10 shrink-0 items-center rounded-lg px-2.5 font-medium text-[#2E3A4D] transition-colors hover:bg-secondary hover:text-primary sm:px-3";

/**
 * Celular: dos filas (logo y cuenta arriba; la navegación en una sola línea abajo, deslizable si no cabe).
 * Escritorio (lg): una fila, con la navegación al centro y la cuenta a la derecha.
 */
export function SiteHeader() {
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-[1248px] flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5 sm:px-8 lg:min-h-20 lg:flex-nowrap lg:py-3">
        <Link href="/" className="order-1 flex min-h-10 shrink-0 items-center gap-2" aria-label="Cumple&Cobra, inicio">
          <Image src="/brand/logo-mark.png" alt="" width={36} height={32} priority className="sm:h-9 sm:w-10" />
          <span className="brand-heading text-lg text-primary sm:text-[1.4rem]">
            Cumple<span className="text-success-strong">&amp;</span>Cobra
          </span>
        </Link>
        <div className="order-2 flex items-center gap-2 lg:order-3">
          <HeaderInbox />
          <HeaderIdentity />
          <WalletConnect />
        </div>
        <nav aria-label="Principal"
          className="order-3 -mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-1 overflow-x-auto px-1.5 text-[0.95rem] [scrollbar-width:none] sm:gap-2 sm:text-base lg:order-2 lg:mx-0 lg:w-auto lg:flex-1 lg:justify-end lg:px-0">
          <Link href="/probar" className="inline-flex min-h-10 shrink-0 items-center rounded-lg bg-success-soft px-2.5 font-bold text-success-strong transition-colors hover:bg-secondary hover:text-primary sm:px-3">
            Pruébalo
          </Link>
          <Link href="/cliente" className={NAV_LINK}>Soy cliente</Link>
          <Link href="/programadores" className={NAV_LINK}>Programadores</Link>
          <span className="hidden shrink-0 rounded-full bg-secondary px-3 py-1 text-sm font-medium text-primary xl:inline">Testnet de Stellar</span>
        </nav>
      </div>
    </header>
  );
}
