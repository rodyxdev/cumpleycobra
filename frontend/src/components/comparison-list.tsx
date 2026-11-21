import { Check, X } from "lucide-react";

export function ComparisonList({ items }: { items: string[] }) {
  return (
    <ol className="divide-y divide-border">
      {items.map((line, i) => {
        const ok = line.trimStart().startsWith("✓");
        const Icon = ok ? Check : X;
        return (
          <li key={i} className="flex items-start gap-3.5 py-4 first:pt-0 last:pb-0 sm:gap-4">
            <span className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full ${ok ? "bg-success-soft text-success-strong" : "bg-danger-soft text-danger"}`}>
              <Icon className="size-4" strokeWidth={3} aria-hidden="true" />
              <span className="sr-only">{ok ? "Cumple:" : "No cumple:"}</span>
            </span>
            <span className="min-w-0 text-base leading-relaxed">{line.trimStart().replace(/^[✓✗]\s*/, "")}</span>
          </li>
        );
      })}
    </ol>
  );
}
