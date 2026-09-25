// Cuándo el cliente puede aprobar manualmente (client_release). Lógica pura, probada en tests/.

export type ApprovalVerdict = { approved: boolean; transaction_hash: string | null };

export type ManualApproval = {
  can: boolean;
  /** Motivo que se explica en la tarjeta, en orden de prioridad. */
  why: "expired" | "approved-unpaid" | "rejected" | null;
};

export function manualApproval(p: {
  status: string | undefined;
  freelancer: string | null | undefined;
  verdicts: ApprovalVerdict[];
  secondsLeft: number | null;
}): ManualApproval {
  if (p.status !== "Funded" || !p.freelancer) return { can: false, why: null };
  if (p.secondsLeft !== null && p.secondsLeft <= 0) return { can: true, why: "expired" };
  // Aprobado sin pago: #9, sin tiempo para el release, trustline o red. El dinero sigue en el contrato.
  if (p.verdicts.some((v) => v.approved && !v.transaction_hash)) return { can: true, why: "approved-unpaid" };
  if (p.verdicts.some((v) => !v.approved)) return { can: true, why: "rejected" };
  return { can: false, why: null };
}
