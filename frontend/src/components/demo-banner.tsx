import { APP_MODE, USDC_FAUCET_URL } from "@/lib/app-mode";

/** Aviso fijo del modo demo: se ve también en celular, donde el chip «Testnet» del encabezado se oculta. */
export function DemoBanner() {
  if (APP_MODE !== "demo") return null;
  return (
    <div className="bg-primary text-primary-foreground" data-testid="aviso-demo">
      <p className="mx-auto max-w-[1248px] px-5 py-2 text-center text-sm leading-snug sm:px-8">
        Demo en la testnet de Stellar: el USDC es de prueba y no tiene valor.{" "}
        <a href={USDC_FAUCET_URL} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-4">
          Consigue USDC de prueba
        </a>
      </p>
    </div>
  );
}
