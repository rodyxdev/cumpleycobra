import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export type EmptyAction = { label: string; href?: string; onClick?: () => void; primary?: boolean };

/** Estado vacío o de error con al menos una salida: nunca una página sin a dónde ir. */
export function EmptyState({
  icon: Icon,
  title,
  children,
  actions = [],
  tone = "neutral",
  testId,
}: {
  icon: LucideIcon;
  title: string;
  children?: React.ReactNode;
  actions?: EmptyAction[];
  tone?: "neutral" | "alert";
  testId?: string;
}) {
  return (
    <Card data-testid={testId}>
      <CardContent className="flex flex-col items-start gap-4 py-2">
        <span className={`grid size-11 place-items-center rounded-full ${tone === "alert" ? "bg-danger-soft text-danger" : "bg-secondary text-primary"}`}>
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <div className="space-y-1.5">
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {children && <div className="max-w-2xl text-base text-muted-foreground">{children}</div>}
        </div>
        {actions.length > 0 && (
          <div className="flex flex-wrap gap-3">
            {actions.map((a) =>
              a.href ? (
                <Button key={a.label} variant={a.primary ? "default" : "outline"} nativeButton={false} render={<Link href={a.href} />}>
                  {a.label}
                </Button>
              ) : (
                <Button key={a.label} variant={a.primary ? "default" : "outline"} onClick={a.onClick}>
                  {a.label}
                </Button>
              ),
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
