"use client";

// Identidad verificada (SEP-10): la wallet firma un reto del backend y la sesión se guarda por
// dirección. Aditivo: crear, depositar, aceptar, entregar y cobrar no la piden.
//   - Pollar: getClient().stellar.sep10.sign (firma en el servidor tras validar que el reto es un
//     SEP-10 inofensivo; verificado en la prueba del paso 1, docs/identidad.md).
//   - Freighter (respaldo): signTransaction de la extensión sobre el mismo reto.

import * as freighter from "@stellar/freighter-api";
import { usePollar } from "@pollar/react";
import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { pollarEnabled, useWallet } from "@/hooks/use-wallet";
import { api, ApiError, type Challenge } from "@/lib/api";
import { WALLET_MODE } from "@/lib/config";
import { sessionIsValid, type Session } from "@/lib/identity";
import { keys, store, useStored } from "@/lib/store";

type Sep10Signer = (challenge: Challenge, address: string) => Promise<string>;

function usePollarSep10(): Sep10Signer {
  const pollar = usePollar();
  return async (c) => {
    const r = await pollar.getClient().stellar.sep10.sign({
      challengeXdr: c.transaction, homeDomains: [c.home_domain], webAuthDomain: c.web_auth_domain,
    });
    if (r.status !== "signed") throw new Error(`Pollar no firmó el reto: ${r.details ?? r.code ?? "error"}`);
    return r.signedXdr;
  };
}

function useFreighterSep10(): Sep10Signer {
  return async (c, address) => {
    const r = await freighter.signTransaction(c.transaction, { networkPassphrase: c.network_passphrase, address });
    if (r.error) throw new Error(`Freighter no firmó el reto: ${r.error.message ?? r.error}`);
    return r.signedTxXdr;
  };
}

// Se elige una sola vez, como useWallet: el orden de los hooks nunca cambia.
const useSep10Signer: () => Sep10Signer = pollarEnabled && WALLET_MODE === "pollar" ? usePollarSep10 : useFreighterSep10;

/** Sesión válida de esa dirección (o null). Se revisa cada minuto por si caduca con la página abierta. */
export function useIdentity(address: string | null | undefined) {
  const stored = useStored<Session>(address ? keys.session(address) : null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  const valid = sessionIsValid(stored, address, now);
  return { session: valid ? stored : null, verified: valid };
}

/** Si el backend dice que la sesión ya no sirve, se borra para volver a pedir la verificación. */
export function dropSessionIfRejected(address: string | null | undefined, e: unknown) {
  if (address && e instanceof ApiError && e.code === "SESSION_REQUIRED") store.clearSession(address);
}

export function IdentityBadge({ className = "" }: { className?: string }) {
  return (
    <span data-testid="identidad-verificada"
      className={`inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-sm font-medium text-primary ${className}`}>
      <ShieldCheck className="size-4" aria-hidden="true" /> Identidad verificada
    </span>
  );
}

export function VerifyIdentityButton({ address, size = "sm", onVerified }: {
  address: string;
  size?: "sm" | "default";
  onVerified?: () => void;
}) {
  const sign = useSep10Signer();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      const challenge = await api.authChallenge(address);
      const signed = await sign(challenge, address);
      store.saveSession(await api.authToken(signed));
      onVerified?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button size={size} variant="outline" data-testid="verificar-identidad" disabled={busy} onClick={verify}>
        <ShieldCheck aria-hidden="true" data-icon="inline-start" />
        {busy ? "Firmando el reto…" : "Verificar identidad"}
      </Button>
      {error && <span role="alert" className="max-w-xs text-xs text-[var(--alert-foreground)]">{error}</span>}
    </span>
  );
}

/** Encabezado: con la wallet conectada, el botón o la insignia. */
export function HeaderIdentity() {
  const wallet = useWallet();
  const { verified } = useIdentity(wallet.address);
  if (!wallet.address || !wallet.supported) return null;
  return verified ? <IdentityBadge /> : <VerifyIdentityButton address={wallet.address} />;
}
