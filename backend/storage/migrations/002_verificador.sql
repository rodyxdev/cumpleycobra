-- Fase 3: cola de trabajos del verificador y entregas en ZIP. Solo agrega tablas.
-- Un trabajo se reclama con FOR UPDATE SKIP LOCKED; si el trabajador muere, vuelve a la cola
-- cuando vence lease_until. `payload`, `progress` y `result` son documentos json.

CREATE TABLE IF NOT EXISTS verifier_jobs (
    id           text PRIMARY KEY,
    kind         text NOT NULL,            -- suite | verify
    task_id      text NOT NULL,
    status       text NOT NULL,            -- queued | running | done | failed
    payload      json NOT NULL,
    progress     json NOT NULL DEFAULT '[]',
    result       json,
    attempts     integer NOT NULL DEFAULT 0,
    lease_id     text,
    lease_until  double precision,
    created_at   double precision NOT NULL,
    updated_at   double precision NOT NULL
);

CREATE INDEX IF NOT EXISTS verifier_jobs_claim ON verifier_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS verifier_jobs_task ON verifier_jobs (task_id, created_at);

CREATE TABLE IF NOT EXISTS verifier_sources (
    id          text PRIMARY KEY,
    task_id     text NOT NULL,
    data        bytea NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
