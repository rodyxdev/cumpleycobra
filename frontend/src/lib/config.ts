// Configuración pública del frontend (solo valores NEXT_PUBLIC_*; nunca llaves privadas).

import { Asset, Networks } from "@stellar/stellar-sdk";

export const CONTRACT_ID =
  process.env.NEXT_PUBLIC_CONTRACT_ID ?? "CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ";
export const RPC_URL = process.env.NEXT_PUBLIC_STELLAR_RPC_URL ?? "https://soroban-testnet.stellar.org";
export const NETWORK_PASSPHRASE = Networks.TESTNET;

// USDC de testnet (Circle): "CÓDIGO:EMISOR".
const [USDC_CODE, USDC_ISSUER] = (
  process.env.NEXT_PUBLIC_USDC_ASSET ?? "USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
).split(":");
export const USDC = { code: USDC_CODE, issuer: USDC_ISSUER };
export const USDC_ASSET = new Asset(USDC_CODE, USDC_ISSUER);

export const POLLAR_API_KEY = process.env.NEXT_PUBLIC_POLLAR_API_KEY ?? "";

/** "pollar" (por defecto) o "freighter" (respaldo: firma con la extensión Freighter). */
export const WALLET_MODE: "pollar" | "freighter" =
  process.env.NEXT_PUBLIC_WALLET === "freighter" ? "freighter" : "pollar";
