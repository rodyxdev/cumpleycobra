// Datos de la tarjeta de veredicto a partir de la respuesta real de /evaluate (nunca del texto de la
// terminal). Lógica pura, probada en tests/.

export type VerdictFields = {
  approved: boolean;
  reason: string;
  comparison: string[];
  security_flags: string[];
  transaction_hash: string | null;
};

export function verdictCardProps(v: VerdictFields) {
  return {
    approved: v.approved,
    reason: v.reason,
    comparison: v.comparison,
    securityFlags: v.security_flags,
    transactionHash: v.transaction_hash,
  };
}
