import { Check, Clock3, Lock, X } from "lucide-react";
import { PROPOSAL_LABEL, type ProposalDisplayState } from "@/lib/proposals";

export function ProposalStatus({ state }: { state: ProposalDisplayState }) {
  const Icon = state === "aceptada" ? Check : state === "rechazada" ? X : state === "cerrada" ? Lock : Clock3;
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-secondary px-3 py-1 text-sm font-medium text-foreground" data-testid="propuesta-estado">
      <Icon className="size-4" aria-hidden="true" />{PROPOSAL_LABEL[state]}
    </span>
  );
}
