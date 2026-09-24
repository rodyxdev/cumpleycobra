export function ComparisonList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((line, i) => {
        const ok = line.trimStart().startsWith("✓");
        return (
          <li key={i} className="flex gap-2 text-sm">
            <span className={ok ? "text-emerald-600" : "text-red-600"}>{ok ? "✓" : "✗"}</span>
            <span>{line.trimStart().replace(/^[✓✗]\s*/, "")}</span>
          </li>
        );
      })}
    </ul>
  );
}
