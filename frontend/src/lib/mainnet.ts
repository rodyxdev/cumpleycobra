// Edición experimental en mainnet (misión especial de Ship It, 27 de noviembre de 2026).
//
// Vive separada de la configuración de testnet (lib/config.ts y lib/soroban.ts) para que
// nada del flujo normal apunte a la red principal por error. Solo usa funciones que firma
// el cliente desde su wallet (Freighter): no hay backend ni llave del árbitro en el navegador.
// Montos mínimos, sin auditoría: ver docs/mainnet.md.

import {
  Address,
  Contract,
  Networks,
  TransactionBuilder,
  nativeToScVal,
  rpc,
  scValToNative,
  type xdr,
} from "@stellar/stellar-sdk";

export const MAINNET = {
  passphrase: Networks.PUBLIC,
  // RPC público de Gateway.fm (gratis, CORS abierto). Respaldo: https://mainnet.sorobanrpc.com
  rpcUrl: "https://soroban-rpc.mainnet.stellar.gateway.fm",
  // Edición ligera (contracts/cumpleycobra-mainnet), desplegada el 27 de noviembre de 2026.
  contractId: "CAAP6Y242FALZ4M46BAICKABWA5T2HG7VL62E3M6BSVG3XI77SA6IYNX",
  // Token del depósito en la edición experimental: XLM nativo (su SAC), para no exigir
  // trustline ni USDC en Stellar a la wallet de prueba. Mismos 7 decimales que USDC.
  token: { symbol: "XLM", sac: "CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA" },
  // SAC del USDC de Circle en mainnet (USDC:GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN),
  // verificado on-chain; es el token de un lanzamiento real.
  usdcSac: "CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75",
  explorer: "https://stellar.expert/explorer/public",
} as const;

export const USDC_UNITS = BigInt(10_000_000); // 7 decimales (igual en XLM y USDC)

const server = new rpc.Server(MAINNET.rpcUrl);

export class MainnetError extends Error {}

// Errores del contrato que pueden salir de las cinco funciones de esta página.
const ERRORS: Record<number, string> = {
  1: "El contrato no está inicializado.",
  3: "El monto debe ser mayor que cero.",
  4: "Ya existe una tarea con ese identificador.",
  5: "La tarea no existe en el contrato.",
  6: "La tarea ya no está depositada (ya se pagó o se reembolsó).",
  7: "Todavía no vence el plazo.",
  8: "Plazo inválido (máximo 28 días desde ahora al prorrogar).",
  9: "El plazo ya venció.",
  12: "Esa dirección no es la del programador registrado.",
  18: "Hay una disputa abierta: el reembolso espera.",
  20: "Los depósitos están en pausa.",
};

function explain(e: unknown): MainnetError {
  const text = e instanceof Error ? e.message : String(e);
  const m = text.match(/Error\(Contract, #(\d+)\)/);
  if (m) return new MainnetError(ERRORS[Number(m[1])] ?? `Error del contrato #${m[1]}.`);
  if (/trustline/i.test(text)) return new MainnetError("Falta la trustline del token en alguna cuenta.");
  if (/balance|insufficient|underfunded/i.test(text)) return new MainnetError("Saldo insuficiente.");
  return new MainnetError(`La red rechazó la transacción: ${text.slice(0, 200)}`);
}

/** "0.02" → 200000n (unidades del token). Sin float: se parte el texto. */
export function parseUsdc(text: string): bigint {
  const clean = text.trim();
  if (!/^\d+(\.\d{1,7})?$/.test(clean)) throw new MainnetError("Monto inválido: usa hasta 7 decimales, por ejemplo 0.02.");
  const [whole, frac = ""] = clean.split(".");
  return BigInt(whole) * USDC_UNITS + BigInt(frac.padEnd(7, "0"));
}

export function formatUsdc(units: bigint): string {
  const whole = units / USDC_UNITS;
  const frac = (units % USDC_UNITS).toString().padStart(7, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : `${whole}`;
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

const str = (s: string) => nativeToScVal(s, { type: "string" });
const i128 = (n: bigint) => nativeToScVal(n, { type: "i128" });
const u64 = (n: bigint) => nativeToScVal(n, { type: "u64" });

/** Argumentos de cada una de las cinco funciones, en el orden del contrato. */
export const CALLS = {
  deposit: (p: { client: string; taskId: string; amount: bigint; deadlineSecs: bigint; rulesHash: string }) =>
    [new Address(p.client).toScVal(), str(p.taskId), i128(p.amount), u64(p.deadlineSecs),
      nativeToScVal(hexToBytes(p.rulesHash), { type: "bytes" })],
  top_up_task: (p: { taskId: string; amount: bigint }) => [str(p.taskId), i128(p.amount)],
  extend_deadline: (p: { taskId: string; extraSecs: bigint }) => [str(p.taskId), u64(p.extraSecs)],
  client_release: (p: { taskId: string; freelancer: string }) => [str(p.taskId), new Address(p.freelancer).toScVal()],
  timeout_refund: (p: { taskId: string }) => [str(p.taskId)],
} as const;

export type MainnetFn = keyof typeof CALLS;

/** Arma la invocación, la prepara contra el RPC (simulación) y devuelve el XDR para firmar. */
export async function buildCall(source: string, method: MainnetFn, args: xdr.ScVal[]): Promise<string> {
  if (!MAINNET.contractId) throw new MainnetError("El contrato de mainnet todavía no está desplegado.");
  try {
    const account = await server.getAccount(source);
    const tx = new TransactionBuilder(account, { fee: "100000", networkPassphrase: MAINNET.passphrase })
      .addOperation(new Contract(MAINNET.contractId).call(method, ...args))
      .setTimeout(120)
      .build();
    return (await server.prepareTransaction(tx)).toXDR();
  } catch (e) {
    throw explain(e);
  }
}

/** Envía la transacción firmada y espera SUCCESS (máximo ~60 s). Devuelve el hash. */
export async function submitAndWait(signedXdr: string): Promise<string> {
  const tx = TransactionBuilder.fromXDR(signedXdr, MAINNET.passphrase);
  const sent = await server.sendTransaction(tx);
  if (sent.status === "ERROR") throw explain(new Error(JSON.stringify(sent.errorResult ?? sent)));
  for (let i = 0; i < 60; i++) {
    const r = await server.getTransaction(sent.hash);
    if (r.status === rpc.Api.GetTransactionStatus.SUCCESS) return sent.hash;
    if (r.status === rpc.Api.GetTransactionStatus.FAILED) throw new MainnetError("La transacción quedó FAILED en la red.");
    await new Promise((res) => setTimeout(res, 1000));
  }
  throw new MainnetError("La transacción no se confirmó a tiempo; revisa el explorador.");
}

export type MainnetTask = {
  client: string;
  freelancer: string | null;
  amount: bigint;
  deadline: number;
  status: string;
};

/** Lee get_task con una simulación (no firma ni gasta). `null` si la tarea no existe. */
export async function readTask(source: string, taskId: string): Promise<MainnetTask | null> {
  if (!MAINNET.contractId) return null;
  try {
    const account = await server.getAccount(source);
    const tx = new TransactionBuilder(account, { fee: "100", networkPassphrase: MAINNET.passphrase })
      .addOperation(new Contract(MAINNET.contractId).call("get_task", str(taskId)))
      .setTimeout(60)
      .build();
    const sim = await server.simulateTransaction(tx);
    if (rpc.Api.isSimulationError(sim)) {
      if (/#5\)/.test(sim.error)) return null;
      throw new Error(sim.error);
    }
    const raw = scValToNative(sim.result!.retval) as Record<string, unknown>;
    const status = Array.isArray(raw.status) ? String(raw.status[0]) : String(raw.status);
    return {
      client: String(raw.client),
      freelancer: raw.freelancer ? String(raw.freelancer) : null,
      amount: BigInt(raw.amount as bigint),
      deadline: Number(raw.deadline),
      status,
    };
  } catch (e) {
    throw explain(e);
  }
}

export const txUrl = (hash: string) => `${MAINNET.explorer}/tx/${hash}`;
export const contractUrl = () => `${MAINNET.explorer}/contract/${MAINNET.contractId}`;
