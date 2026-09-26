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
/** Estado que se muestra: "cerrada" se calcula aquí (pendiente, pero la tarea la tomó otro); no se guarda. */
export type ProposalDisplayState = ProposalState | "cerrada";
export const PROPOSAL_LABEL: Record<ProposalDisplayState, string> = {
  pendiente: "Pendiente", aceptada: "Aceptada", rechazada: "Rechazada",
  cerrada: "Cerrada: la tomó otro programador",
};
export function proposalDisplayState(
  proposal: { estado: ProposalState; programador: string }, freelancerAddress: string | null | undefined,
): ProposalDisplayState {
  return proposal.estado === "pendiente" && !!freelancerAddress && freelancerAddress !== proposal.programador
    ? "cerrada" : proposal.estado;
}
export function taskAvailableForProposal(
  task: { client_address: string; freelancer_address: string | null }, address: string,
): boolean {
  return task.client_address === address && task.freelancer_address === null;
}
/** Pendiente y la tarea libre o ya amarrada a este destinatario (el backend devuelve el mismo token). */
export function canDecideProposal(proposal: Pick<InboxProposal, "estado" | "programador" | "tarea">): boolean {
  const bound = proposal.tarea.freelancer_address;
  return proposal.estado === "pendiente" && (bound === null || bound === proposal.programador);
}
