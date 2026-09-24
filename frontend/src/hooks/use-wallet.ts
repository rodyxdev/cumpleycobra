"use client";

// Una sola interfaz de wallet para las vistas:
//   - Pollar (por defecto): login, dirección, trustline y firma.
//       * wallet custodial (internal): getClient().signTx(xdr) firma en el servidor de Pollar y
//         devuelve un fee-bump patrocinado por la app; el frontend lo envía al RPC.
//       * wallet externa (Freighter, Albedo… conectada por Pollar): signTx + envío al RPC.
//   - Freighter (NEXT_PUBLIC_WALLET=freighter): respaldo; la extensión firma deposit y
//     client_release. Si hay sesión de Pollar con la misma dirección, Pollar activa la trustline.
// Después de enviar, siempre se consulta el RPC hasta SUCCESS.

import * as freighter from "@stellar/freighter-api";
import { usePollar } from "@pollar/react";
import { FeeBumpTransaction, TransactionBuilder } from "@stellar/stellar-sdk";
import { useSyncExternalStore } from "react";

import { NETWORK_PASSPHRASE, POLLAR_API_KEY, USDC, WALLET_MODE } from "@/lib/config";
import { buildUsdcTrustline, ChainError, submitSigned, waitForSuccess } from "@/lib/soroban";

export type Wallet = {
  mode: "pollar" | "freighter";
  address: string | null;
  /** internal (custodial de Pollar), smart (passkey, C…), external o freighter. */
  custody: string | null;
  /** Solo las cuentas clásicas (G…) sirven para este contrato y para la trustline de USDC. */
  supported: boolean;
  connect: () => void;
  /** Firma, envía y espera SUCCESS. Devuelve el hash. */
  signAndSend: (unsignedXdr: string) => Promise<string>;
  activateUsdc: () => Promise<void>;
};

// --- Dirección de Freighter compartida entre componentes -----------------------------
let freighterAddress: string | null = null;
const listeners = new Set<() => void>();
const freighterStore = {
  subscribe: (cb: () => void) => {
    listeners.add(cb);
    return () => listeners.delete(cb);
  },
  get: () => freighterAddress,
  set: (a: string | null) => {
    freighterAddress = a;
    listeners.forEach((l) => l());
  },
};

async function connectFreighter(): Promise<void> {
  const conn = await freighter.isConnected();
  if (!conn.isConnected) throw new ChainError("No se encontró la extensión Freighter en este navegador.");
  const access = await freighter.requestAccess();
  if (access.error) throw new ChainError(`Freighter no dio acceso: ${access.error.message ?? access.error}`);
  freighterStore.set(access.address);
}

async function freighterSignAndSend(xdr: string, address: string): Promise<string> {
  const signed = await freighter.signTransaction(xdr, { networkPassphrase: NETWORK_PASSPHRASE, address });
  if (signed.error) throw new ChainError(`Freighter no firmó: ${signed.error.message ?? signed.error}`);
  const hash = await submitSigned(signed.signedTxXdr);
  await waitForSuccess(hash);
  return hash;
}

const isClassic = (a: string | null | undefined) => !!a && /^G[A-Z2-7]{55}$/.test(a);

// --- Con Pollar --------------------------------------------------------------------
function usePollarWallet(): Wallet {
  const pollar = usePollar();
  const fAddress = useSyncExternalStore(freighterStore.subscribe, freighterStore.get, () => null);
  const pAddress = pollar.isAuthenticated ? (pollar.wallet?.address ?? null) : null;
  const custody = pollar.wallet?.custody ?? null;

  if (WALLET_MODE === "freighter") {
    return {
      mode: "freighter",
      address: fAddress,
      custody: fAddress ? "freighter" : null,
      supported: isClassic(fAddress),
      connect: () => void connectFreighter().catch(() => undefined),
      signAndSend: (xdr) => {
        if (!fAddress) throw new ChainError("Conecta Freighter primero.");
        return freighterSignAndSend(xdr, fAddress);
      },
      activateUsdc: async () => {
        if (!fAddress) throw new ChainError("Conecta Freighter primero.");
        if (pAddress === fAddress) return pollarTrustline(pollar);
        await freighterSignAndSend(await buildUsdcTrustline(fAddress), fAddress);
      },
    };
  }

  return {
    mode: "pollar",
    address: pAddress,
    custody,
    supported: isClassic(pAddress),
    connect: () => pollar.openLoginModal(),
    signAndSend: async (xdr) => {
      if (!pollar.isAuthenticated || !pAddress) throw new ChainError("Inicia sesión con Pollar primero.");
      if (!pollar.verified) throw new ChainError("La sesión de Pollar todavía se está confirmando; intenta en unos segundos.");
      // Las wallets custodiales de Pollar no tienen XLM (Pollar patrocina sus reservas). El
      // client.signTx de @pollar/core firma en el servidor y, con el patrocinio del dashboard,
      // devuelve un fee-bump pagado por la gas wallet de la app; aquí solo se envía al RPC.
      // (signAndSubmitTx no aplicó el patrocinio y la red respondió txInsufficientBalance.)
      const signed = custody === "external" ? await pollar.signTx(xdr) : await pollar.getClient().signTx(xdr);
      if (signed.status !== "signed") {
        throw new ChainError(`Pollar no firmó: ${signed.message ?? signed.details ?? signed.code ?? "error"}`);
      }
      const feeBump = TransactionBuilder.fromXDR(signed.signedXdr, NETWORK_PASSPHRASE) instanceof FeeBumpTransaction;
      console.info("[cumpleycobra] firma de Pollar", { custody, sponsored: signed.sponsored ?? null, feeBump });
      let hash: string;
      try {
        hash = await submitSigned(signed.signedXdr);
      } catch (e) {
        if (!feeBump && /InsufficientBalance/.test(String(e))) {
          throw new ChainError(
            `Pollar firmó sin patrocinar la comisión (sponsored=${signed.sponsored ?? "sin dato"}) y la wallet no tiene XLM. ` +
              "Activa el patrocinio en el dashboard (Treasury → Sponsorship) o fondea la wallet con XLM.",
          );
        }
        throw e;
      }
      await waitForSuccess(hash);
      return hash;
    },
    activateUsdc: () => pollarTrustline(pollar),
  };
}

async function pollarTrustline(pollar: ReturnType<typeof usePollar>): Promise<void> {
  const out = await pollar.setTrustline(USDC);
  if (out.status === "error") throw new ChainError(`Pollar no activó USDC: ${out.details ?? "error"}`);
  if (out.hash) await waitForSuccess(out.hash);
}

// --- Sin API key de Pollar: solo Freighter ----------------------------------------------
function useFreighterOnlyWallet(): Wallet {
  const fAddress = useSyncExternalStore(freighterStore.subscribe, freighterStore.get, () => null);
  return {
    mode: "freighter",
    address: fAddress,
    custody: fAddress ? "freighter" : null,
    supported: isClassic(fAddress),
    connect: () => void connectFreighter().catch(() => undefined),
    signAndSend: (xdr) => {
      if (!fAddress) throw new ChainError("Conecta Freighter primero.");
      return freighterSignAndSend(xdr, fAddress);
    },
    activateUsdc: async () => {
      if (!fAddress) throw new ChainError("Conecta Freighter primero.");
      await freighterSignAndSend(await buildUsdcTrustline(fAddress), fAddress);
    },
  };
}

// Se elige una sola vez, a nivel de módulo: el orden de los hooks nunca cambia.
export const useWallet: () => Wallet = POLLAR_API_KEY ? usePollarWallet : useFreighterOnlyWallet;
export const pollarEnabled = !!POLLAR_API_KEY;
