/** Datos públicos de una propuesta; los tokens solo viajan en respuestas autorizadas. */
export type ProposalState = "pendiente" | "aceptada" | "rechazada";
export type Proposal = {
  id: string;
  task_id: string;
  programador: string;
  estado: ProposalState;
  created_at: number;
};
export type InboxProposal = Proposal & {
  tarea: {
    description: string;
    criteria: string[];
    amount: number;
    freelancer_address: string | null;
    onchain: { amount: number; status: "Funded" | "Released" | "Refunded" } | null;
    onchain_error: string | null;
  };
};
export const PROPOSAL_LABEL: Record<ProposalState, string> = {
  pendiente: "Pendiente", aceptada: "Aceptada", rechazada: "Rechazada",
};
export function taskAvailableForProposal(
  task: { client_address: string; freelancer_address: string | null }, address: string,
): boolean {
  return task.client_address === address && task.freelancer_address === null;
}
export function canDecideProposal(proposal: InboxProposal): boolean {
  return proposal.estado === "pendiente" && proposal.tarea.freelancer_address === null;
}
