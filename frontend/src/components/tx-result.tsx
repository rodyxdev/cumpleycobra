import { explorerTx } from "@/lib/format";

export type TxState =
  | { phase: "idle" }
  | { phase: "signing" }
  | { phase: "done"; hash: string }
  | { phase: "error"; message: string };

/** Estado real de una transacción firmada por la wallet: nada se muestra antes de que ocurra. */
export function TxResult({ state, label }: { state: TxState; label: string }) {
  if (state.phase === "idle") return null;
  if (state.phase === "signing") {
    return <p className="text-sm text-muted-foreground">{label}: firmando con la wallet y esperando la confirmación de la red…</p>;
  }
  if (state.phase === "error") return <p className="text-sm text-red-600">{label}: {state.message}</p>;
  return (
    <p className="text-sm" data-testid={`tx-${label}`}>
      {label} confirmado en la red:{" "}
      <a className="font-mono text-xs text-sky-700 underline" href={explorerTx(state.hash)} target="_blank" rel="noreferrer">
        {state.hash}
      </a>
    </p>
  );
}
