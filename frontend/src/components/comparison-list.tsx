import { Check, X } from "lucide-react";

export function ComparisonList({ items }: { items: string[] }) {
  return (
    <ul className="divide-y divide-border">
      {items.map((line, i) => {
        const ok = line.trimStart().startsWith("✓");
        const Icon = ok ? Check : X;
        return (
          <li key={i} className="flex items-start gap-3 py-4 first:pt-0 last:pb-0 sm:gap-4">
            <span className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full ${ok ? "bg-secondary text-primary" : "bg-[var(--alert-background)] text-[var(--alert-foreground)]"}`}>
              <Icon className="size-4" aria-hidden="true" />
              <span className="sr-only">{ok ? "Cumple:" : "No cumple:"}</span>
            </span>
            <span className="min-w-0 text-base leading-relaxed">{line.trimStart().replace(/^[✓✗]\s*/, "")}</span>
          </li>
        );
      })}
    </ul>
  );
}
