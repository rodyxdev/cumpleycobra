"use client";

import { useState } from "react";

import { dropSessionIfRejected, useIdentity, VerifyIdentityButton } from "@/components/identity";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useWallet } from "@/hooks/use-wallet";
import { api, ApiError, type ProfileFields } from "@/lib/api";
import { MAX_BIO, MAX_NAME, MAX_SKILLS, parseSkills, profileProblem } from "@/lib/identity";

/** Solo lo ve el dueño de la dirección (wallet conectada) y solo guarda con su identidad verificada. */
export function ProfileEditor({ address, initial, onSaved }: {
  address: string;
  initial: ProfileFields;
  onSaved: (p: ProfileFields) => void;
}) {
  const wallet = useWallet();
  const { session } = useIdentity(address);
  const [nombre, setNombre] = useState(initial.nombre ?? "");
  const [skills, setSkills] = useState(initial.habilidades.join(", "));
  const [bio, setBio] = useState(initial.bio ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (wallet.address !== address) return null;

  if (!session) {
    return (
      <Card data-testid="perfil-requiere-identidad">
        <CardHeader>
          <CardTitle>Es tu perfil</CardTitle>
          <CardDescription>Verifica tu identidad con tu wallet para editar tu nombre, habilidades y bio.</CardDescription>
        </CardHeader>
        <CardContent><VerifyIdentityButton address={address} size="default" /></CardContent>
      </Card>
    );
  }

  const list = parseSkills(skills);
  const problem = profileProblem(nombre, list, bio);

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api.putProfile(session!.token, { nombre: nombre.trim() || null, habilidades: list, bio: bio.trim() || null });
      onSaved({ nombre: r.nombre, habilidades: r.habilidades, bio: r.bio });
      setSaved(true);
    } catch (e) {
      dropSessionIfRejected(address, e);
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="editar-perfil">
      <CardHeader>
        <CardTitle>Edita tu perfil</CardTitle>
        <CardDescription>Se publica junto a tu historial verificable. Solo tú puedes cambiarlo, con tu identidad verificada.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="perfil-nombre">Nombre</Label>
          <Input id="perfil-nombre" value={nombre} maxLength={MAX_NAME} disabled={busy} onChange={(e) => setNombre(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="perfil-habilidades">Habilidades (separadas por comas, hasta {MAX_SKILLS})</Label>
          <Input id="perfil-habilidades" value={skills} disabled={busy} placeholder="Python, FastAPI, Automatización"
            onChange={(e) => setSkills(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="perfil-bio">Bio</Label>
          <Textarea id="perfil-bio" rows={3} value={bio} maxLength={MAX_BIO} disabled={busy} onChange={(e) => setBio(e.target.value)} />
          <p className="text-right text-xs text-muted-foreground">{bio.length}/{MAX_BIO}</p>
        </div>
        {problem && <p className="text-sm text-[var(--alert-foreground)]">{problem}</p>}
        {error && <p role="alert" className="text-sm text-[var(--alert-foreground)]">{error}</p>}
        {saved && <p role="status" className="text-sm text-primary" data-testid="perfil-guardado">Perfil guardado.</p>}
        <Button data-testid="guardar-perfil" disabled={busy || !!problem} onClick={save}>
          {busy ? "Guardando…" : "Guardar perfil"}
        </Button>
      </CardContent>
    </Card>
  );
}
