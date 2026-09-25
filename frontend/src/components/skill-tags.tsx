/** Habilidades del perfil como etiquetas. */
export function SkillTags({ skills }: { skills: string[] }) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Habilidades" data-testid="habilidades">
      {skills.map((s) => (
        <li key={s} className="rounded-full border border-primary/25 bg-secondary px-3 py-1 text-sm text-primary">{s}</li>
      ))}
    </ul>
  );
}
