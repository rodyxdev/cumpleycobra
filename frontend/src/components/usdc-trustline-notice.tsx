/** Aviso cuando aceptar responde NO_USDC_TRUSTLINE: el mismo en el panel de aceptar y en el buzón. */
export function UsdcTrustlineNotice() {
  return (
    <div className="rounded-md border border-[var(--alert)] bg-[var(--alert-background)] p-3 text-sm text-[var(--alert-foreground)]">
      <div className="font-medium">Activa USDC antes de continuar</div>
      Tu cuenta no tiene trustline de USDC, así que no podría recibir el pago. Actívala y vuelve a aceptar.
    </div>
  );
}
