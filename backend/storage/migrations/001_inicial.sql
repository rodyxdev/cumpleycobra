-- Esquema inicial: un documento por entidad, igual que en state.json.
-- `json` (no `jsonb`) a propósito: conserva el orden de las claves, y el backend usa el orden de
-- inserción (por ejemplo, la última entrega aprobada en task["codes"]).
-- `seq` conserva el orden en que se crearon las filas, como el diccionario de state.json.
-- Las migraciones solo agregan: nunca borran ni cambian columnas que use una versión anterior.

CREATE TABLE IF NOT EXISTS tasks (
    id          text PRIMARY KEY,
    seq         bigserial NOT NULL,
    doc         json NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS profiles (
    id          text PRIMARY KEY,
    seq         bigserial NOT NULL,
    doc         json NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS proposals (
    id          text PRIMARY KEY,
    seq         bigserial NOT NULL,
    doc         json NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS proposals_task_id ON proposals ((doc ->> 'task_id'));
CREATE INDEX IF NOT EXISTS proposals_programador ON proposals ((doc ->> 'programador'));

-- Retos SEP-10: de un solo uso y válidos 5 minutos. En memoria se perdían al reiniciar y no se
-- compartían entre instancias.
CREATE TABLE IF NOT EXISTS sep10_challenges (
    nonce       text PRIMARY KEY,
    address     text NOT NULL,
    expires_at  double precision NOT NULL,
    used        boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
