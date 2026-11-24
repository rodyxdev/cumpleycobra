import { APP_MODE, USDC_FAUCET_URL } from "@/lib/app-mode";

/** Aviso fijo del modo demo: se ve también en celular, donde el chip «Testnet» del encabezado se oculta. */
export function DemoBanner() {
  if (APP_MODE !== "demo") return null;
  return (
    <div className="bg-primary text-primary-foreground" data-testid="aviso-demo">
      <p className="mx-auto flex max-w-[1248px] flex-wrap items-center justify-center gap-x-2 px-4 py-0.5 text-center text-[0.8rem] leading-snug sm:px-8 sm:text-sm">
        <span>
          <span className="sm:hidden">Testnet: el USDC es de prueba.</span>
          <span className="hidden sm:inline">Demo en la testnet de Stellar: el USDC es de prueba y no tiene valor.</span>
        </span>
        <a href={USDC_FAUCET_URL} target="_blank" rel="noreferrer"
          className="inline-flex min-h-10 items-center font-semibold underline underline-offset-4">
          <span className="sm:hidden">Conseguir USDC</span>
          <span className="hidden sm:inline">Consigue USDC de prueba</span>
        </a>
      </p>
    </div>
  );
}
