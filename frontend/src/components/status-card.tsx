import { Clock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { TaskView } from "@/lib/api";
import { formatCountdown, formatUsdc, STATUS_LABEL } from "@/lib/format";

/** Estado y monto leídos del contrato (no del backend), con la cuenta regresiva del plazo. */
export function StatusCard({ task, secondsLeft }: { task: TaskView; secondsLeft: number | null }) {
  const onchain = task.onchain;
  const status = onchain?.status;
  const variant = status === "Released" ? "default" : status === "Refunded" ? "secondary" : "outline";

  return (
    <Card size="sm">
      <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <div className="text-xs text-muted-foreground">Estado en el contrato</div>
          <div className="mt-1" data-testid="estado">
            {onchain ? (
              <Badge variant={variant}>{STATUS_LABEL[onchain.status] ?? onchain.status}</Badge>
            ) : (
              <Badge variant="outline">Sin depósito</Badge>
            )}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Monto en el contrato</div>
          <div className="mt-1 font-medium">{onchain ? formatUsdc(onchain.amount) : "—"}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Plazo restante</div>
          <div className="mt-1 flex items-center gap-1.5 font-mono font-medium tabular-nums" data-testid="plazo">
            <Clock className="size-3.5 text-muted-foreground" />
            {onchain && status === "Funded" && secondsLeft !== null
              ? secondsLeft > 0
                ? formatCountdown(secondsLeft)
                : "vencido"
              : "—"}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Envíos usados</div>
          <div className="mt-1 font-medium">
            {task.submissions_used} de {task.max_submissions}
          </div>
        </div>
        {task.onchain_error && (
          <div className="w-full text-xs text-red-600">No se pudo leer el contrato: {task.onchain_error}</div>
        )}
      </CardContent>
    </Card>
  );
}
