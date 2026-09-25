import { Check, Clock3, X } from "lucide-react";
import { PROPOSAL_LABEL, type ProposalState } from "@/lib/proposals";

export function ProposalStatus({ state }: { state: ProposalState }) {
  const Icon = state === "aceptada" ? Check : state === "rechazada" ? X : Clock3;
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-secondary px-3 py-1 text-sm font-medium text-foreground" data-testid="propuesta-estado">
      <Icon className="size-4" aria-hidden="true" />{PROPOSAL_LABEL[state]}
    </span>
  );
}
