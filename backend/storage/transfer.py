"""Pasa el estado entre state.json y Postgres, en los dos sentidos.

Uso (desde la raíz, con DATABASE_URL definida; también dentro de la imagen de la API):
  python -m backend.storage.transfer importar backend/state.json
  python -m backend.storage.transfer exportar respaldo-state.json
  python -m backend.storage.transfer contar

`importar` se niega si la base ya tiene datos (usa --forzar para sobrescribir documentos con el
mismo id). `exportar` escribe el mismo formato que StateStore: es el camino de regreso a JSON.
Nunca imprime documentos (tienen tokens): solo conteos.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from backend.storage.postgres import TABLES, PostgresStore


def counts(store: PostgresStore) -> dict[str, int]:
    with store.pool.connection() as conn:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def importar(store: PostgresStore, path: Path, forzar: bool) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if any(counts(store).values()) and not forzar:
        raise SystemExit("La base ya tiene datos; usa --forzar para sobrescribir documentos con el mismo id.")
    token = store.begin()
    try:
        for table in TABLES:
            mapping = getattr(store, table)
            for key, doc in (data.get(table) or {}).items():
                mapping[key] = doc  # en el orden del archivo: `seq` conserva el orden del dict
        store.save()
    finally:
        store.end(token)
    return counts(store)


def exportar(store: PostgresStore, path: Path) -> dict[str, int]:
    token = store.begin()
    try:
        data = {"version": 1, **{t: dict(getattr(store, t).items()) for t in TABLES}}
    finally:
        store.end(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return {t: len(data[t]) for t in TABLES}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="accion", required=True)
    imp = sub.add_parser("importar")
    imp.add_argument("archivo", type=Path)
    imp.add_argument("--forzar", action="store_true")
    exp = sub.add_parser("exportar")
    exp.add_argument("archivo", type=Path)
    sub.add_parser("contar")
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Falta DATABASE_URL")
    store = PostgresStore(url, max_size=2)
    try:
        if args.accion == "importar":
            result = importar(store, args.archivo, args.forzar)
        elif args.accion == "exportar":
            result = exportar(store, args.archivo)
        else:
            result = counts(store)
    finally:
        store.close()
    print(", ".join(f"{t}: {n}" for t, n in result.items()))


if __name__ == "__main__":
    main()
