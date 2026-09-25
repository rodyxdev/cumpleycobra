// Transacciones del contrato desde el navegador: se arman con @stellar/stellar-sdk, se preparan
// contra el RPC (simulación: footprint, recursos y autorizaciones) y la wallet solo firma.
// El frontend nunca ve llaves privadas.

import {
  Address,
  Contract,
  Operation,
  TransactionBuilder,
  nativeToScVal,
  rpc,
  type FeeBumpTransaction,
  type Transaction,
} from "@stellar/stellar-sdk";

import { CONTRACT_ID, NETWORK_PASSPHRASE, RPC_URL, USDC_ASSET } from "@/lib/config";
import { sendRejection } from "@/lib/send-status";

export const server = new rpc.Server(RPC_URL);

// Números de error del contrato (contracts/cumpleycobra/src/lib.rs).
const CONTRACT_ERRORS: Record<number, string> = {
  1: "El contrato no está inicializado.",
  3: "El monto debe ser mayor que cero.",
  4: "Esa tarea ya tiene un depósito.",
  5: "La tarea no existe en el contrato.",
  6: "La tarea ya no está depositada (ya se pagó o se reembolsó).",
  7: "Todavía no vence el plazo.",
  8: "Plazo inválido.",
  9: "El plazo ya venció.",
};

export class ChainError extends Error {}

function explain(e: unknown): ChainError {
  const text = e instanceof Error ? e.message : String(e);
  const m = text.match(/Error\(Contract, #(\d+)\)/);
  if (m) return new ChainError(CONTRACT_ERRORS[Number(m[1])] ?? `Error del contrato #${m[1]}.`);
  if (/trustline/i.test(text)) return new ChainError("Falta la trustline de USDC en alguna de las cuentas.");
  if (/balance|insufficient|underfunded/i.test(text)) return new ChainError("Saldo insuficiente para esta operación.");
  if (/not found|404/i.test(text) && /account/i.test(text))
    return new ChainError("La cuenta de la wallet todavía no existe en la red.");
  return new ChainError(`La red rechazó la transacción: ${text.slice(0, 200)}`);
}

async function prepared(source: string, op: ReturnType<Contract["call"]>): Promise<string> {
  try {
    const account = await server.getAccount(source);
    const tx = new TransactionBuilder(account, { fee: "100000", networkPassphrase: NETWORK_PASSPHRASE })
      .addOperation(op)
      .setTimeout(120)
      .build();
    const ready = await server.prepareTransaction(tx);
    return ready.toXDR();
  } catch (e) {
    throw explain(e);
  }
}

/** deposit(client, task_id, amount, deadline_secs, rules_hash), listo para firmar por el cliente. */
export function buildDeposit(p: {
  client: string;
  taskId: string;
  amount: number;
  deadlineSecs: number;
  rulesHash: string;
}): Promise<string> {
  const op = new Contract(CONTRACT_ID).call(
    "deposit",
    new Address(p.client).toScVal(),
    nativeToScVal(p.taskId, { type: "string" }),
    nativeToScVal(BigInt(p.amount), { type: "i128" }),
    nativeToScVal(BigInt(p.deadlineSecs), { type: "u64" }),
    nativeToScVal(hexToBytes(p.rulesHash), { type: "bytes" }),
  );
  return prepared(p.client, op);
}

/** client_release(task_id, freelancer): aprobación manual del cliente. */
export function buildClientRelease(p: { client: string; taskId: string; freelancer: string }): Promise<string> {
  const op = new Contract(CONTRACT_ID).call(
    "client_release",
    nativeToScVal(p.taskId, { type: "string" }),
    new Address(p.freelancer).toScVal(),
  );
  return prepared(p.client, op);
}

/** change_trust de USDC (solo para el respaldo con Freighter; Pollar tiene su propio setTrustline). */
export async function buildUsdcTrustline(address: string): Promise<string> {
  try {
    const account = await server.getAccount(address);
    return new TransactionBuilder(account, { fee: "100000", networkPassphrase: NETWORK_PASSPHRASE })
      .addOperation(Operation.changeTrust({ asset: USDC_ASSET }))
      .setTimeout(120)
      .build()
      .toXDR();
  } catch (e) {
    throw explain(e);
  }
}

export type UsdcStatus = { exists: boolean; trustline: boolean; units: number };

/** Trustline y saldo de USDC de una cuenta clásica (G…), leídos del RPC. */
export async function usdcStatus(address: string): Promise<UsdcStatus> {
  try {
    await server.getAccount(address);
  } catch {
    return { exists: false, trustline: false, units: 0 };
  }
  try {
    const r = await server.getAssetBalance(address, USDC_ASSET, NETWORK_PASSPHRASE);
    return { exists: true, trustline: !!r.balanceEntry, units: r.balanceEntry ? Number(r.balanceEntry.amount) : 0 };
  } catch (e) {
    // stellar-sdk 17 lanza "Trustline for … not found" en lugar de devolver balanceEntry vacío.
    if (/trustline/i.test(String(e))) return { exists: true, trustline: false, units: 0 };
    throw e;
  }
}

/** Envía una transacción ya firmada al RPC y devuelve su hash. */
export async function submitSigned(signedXdr: string): Promise<string> {
  const tx: Transaction | FeeBumpTransaction = TransactionBuilder.fromXDR(signedXdr, NETWORK_PASSPHRASE);
  const sent = await server.sendTransaction(tx);
  const rejection = sendRejection(sent.status, sent.status === "ERROR" ? sent.errorResult?.result.type : undefined);
  if (rejection) throw new ChainError(rejection);
  return sent.hash;
}

/** Consulta el RPC hasta SUCCESS o FAILED (máximo ~60 s). */
export async function waitForSuccess(hash: string): Promise<void> {
  for (let i = 0; i < 60; i++) {
    const r = await server.getTransaction(hash);
    if (r.status === rpc.Api.GetTransactionStatus.SUCCESS) return;
    if (r.status === rpc.Api.GetTransactionStatus.FAILED) throw new ChainError("La transacción quedó FAILED en la red.");
    await new Promise((res) => setTimeout(res, 1000));
  }
  throw new ChainError("La transacción no se confirmó a tiempo; revisa el explorador.");
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}
