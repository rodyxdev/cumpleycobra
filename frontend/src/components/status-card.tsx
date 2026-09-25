import { Clock, CircleCheck, CircleDashed, RotateCcw } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { TaskView } from "@/lib/api";
import { formatCountdown, STATUS_LABEL } from "@/lib/format";
import { Money, FxNotice } from "@/components/money";

/** Estado y monto leídos del contrato, con la cuenta regresiva del plazo. */
export function StatusCard({ task, secondsLeft }: { task: TaskView; secondsLeft: number | null }) {
  const onchain = task.onchain;
  const status = onchain?.status;
  const Icon = status === "Released" ? CircleCheck : status === "Refunded" ? RotateCcw : CircleDashed;
  return (
    <Card size="sm" className="bg-transparent">
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-x-6 gap-y-7 md:grid-cols-[1fr_1.35fr_1fr_.75fr]">
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Estado en el contrato</p>
            <div className="flex items-center gap-2 text-xl font-semibold tracking-tight" data-testid="estado">
              <Icon className={`size-5 shrink-0 ${status === "Released" ? "text-primary" : "text-muted-foreground"}`} aria-hidden="true" />
              {onchain ? STATUS_LABEL[onchain.status] ?? onchain.status : "Sin depósito"}
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Monto en el contrato</p>
            <div className="money-prominent">{onchain ? <Money units={onchain.amount} /> : "—"}</div>
          </div>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Plazo restante</p>
            <div className="flex items-center gap-2 text-2xl font-medium tabular-nums tracking-tight" data-testid="plazo">
              <Clock className="size-5 text-muted-foreground" aria-hidden="true" />
              {onchain && status === "Funded" && secondsLeft !== null
                ? secondsLeft > 0 ? formatCountdown(secondsLeft) : "vencido" : "—"}
            </div>
          </div>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Envíos usados</p>
            <p className="text-2xl font-medium tabular-nums tracking-tight">{task.submissions_used} <span className="text-base font-normal text-muted-foreground">de {task.max_submissions}</span></p>
          </div>
        </div>
        {task.onchain_error && <p className="alert-panel text-base">No se pudo leer el contrato: {task.onchain_error}</p>}
        <div className="border-t pt-4 [&>p]:text-sm"><FxNotice /></div>
      </CardContent>
    </Card>
  );
}
