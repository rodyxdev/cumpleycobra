import { resolveApiUrl } from "@/lib/api-url";
import type { Proposal, InboxProposal } from "@/lib/proposals";

// Cliente del backend de Cumple&Cobra. El frontend nunca toca llaves ni la API de Gemini.

export const API_URL = resolveApiUrl(process.env.NEXT_PUBLIC_API_URL, process.env.NODE_ENV);

export type Example = { input: string; output: string };
export type Fx = { rate: string; as_of: string; source: string; fallback: boolean };
export type CriterionReview = { index: number; vague: boolean; suggestion: string | null };

export type Spec = {
  description: string;
  criteria: string[];
  language: string;
  allowed_deps: string[];
  examples: Example[];
  /** Perfil web (fase 3): páginas que se revisan en el navegador. */
  web?: WebPages | null;
};

export type WebPages = { pages: string[] };

export type Caso = { id: string; nombre: string; principal: boolean; codigo: string };

export type Demo = { raw_request: string; spec: Spec; casos: Caso[] };

export type OnchainTask = {
  task_id: string;
  client: string;
  freelancer: string | null;
  amount: number;
  deadline: number;
  rules_hash: string;
  status: "Funded" | "Released" | "Refunded";
};

/** Fase 3: lo que la entrega debe exponer para verificarla ejecutando. */
export type InterfaceSymbol = { module: string; name: string; kind: "function" | "class"; signature: string; description?: string };
export type Interface = { language: "python"; symbols: InterfaceSymbol[] };

/** Plan público de la suite oculta: nunca trae el código de los tests. */
export type SuitePlan = {
  status: "pendiente" | "validando" | "lista" | "rechazada";
  suite_hash: string | null;
  /** "web": los chequeos son públicos y corren en un navegador real. */
  profile?: "web";
  /** Motivo, si la suite quedó rechazada (p. ej. el verificador no pudo ejecutar). */
  error?: string | null;
  /** Intentos extra que todavía puede pedir el cliente si la suite quedó rechazada. */
  retries_left?: number;
  criteria: {
    index: number;
    tipo: "test" | "lectura" | "navegador" | "visual" | null;
    plan: string[];
    problems: string[];
    checks?: WebCheck[];
  }[];
};

export type WebCheck = { id: string; kind: string; page: string; args: string[] };

/** Captura de una entrega web; `url` es relativa a la API y vence a los 15 minutos. */
export type Screenshot = { id: string; page: string; viewport: "desktop" | "mobile" | string; label: string; sha256: string; url?: string | null };

export type VerificationSource =
  | { kind: "code"; code: string }
  | { kind: "zip"; zip_b64: string }
  | { kind: "github_public"; repo: string; sha: string };

export type VerificationStatus = {
  verification_id: string;
  task_id: string;
  status: "queued" | "running" | "done" | "failed";
  created_at: number;
  updated_at: number;
  progress: { stage: string; label: string; detail: string; at: number }[];
  submissions_used: number;
  result?: Verdict & { verdict_version?: number; workspace_hash?: string; suite_hash?: string };
  error?: string;
  message?: string;
};

export type TaskView = Spec & {
  task_id: string;
  raw_request: string;
  rules_hash: string;
  amount: number;
  deadline_minutes: number;
  client_address: string;
  freelancer_address: string | null;
  submissions_used: number;
  max_submissions: number;
  onchain: OnchainTask | null;
  seconds_left: number | null;
  onchain_error: string | null;
  latest_code_hash?: string | null;
  consented_code_hash?: string | null;
  latest_rejected?: boolean;
  /** Calificación del cliente, si ya calificó (pública: aparece en el perfil del programador). */
  rating?: Rating | null;
  /** Fase 3: "execution" si la tarea se verifica ejecutando el código. */
  verification?: "static" | "execution";
  interface?: Interface;
  suite?: SuitePlan | null;
};

export type Rating = { estrellas: number; comentario: string | null };

/** Métricas de un programador: solo tareas Released confirmadas en el contrato. */
export type ProgrammerSummary = {
  address: string;
  engine_paid: number;
  manual_paid: number;
  distinct_clients: number;
  rating_average: number | null;
  rating_count: number;
  /** Solo si el dueño publicó su perfil con identidad verificada (SEP-10). */
  nombre?: string | null;
  habilidades?: string[];
  bio?: string | null;
  identidad_verificada?: boolean;
};

export type Challenge = { transaction: string; network_passphrase: string; home_domain: string; web_auth_domain: string; expires_in: number };
export type ProfileFields = { nombre: string | null; habilidades: string[]; bio: string | null };

export type PaidTask = {
  task_id: string;
  description: string;
  criteria_count: number;
  amount: number;
  paid_by: "motor" | "manual";
  transaction_hash: string | null;
  paid_at: string | null;
  rating: Rating | null;
};

export type ProgrammerProfile = ProgrammerSummary & { history: PaidTask[] };

export type CreatedTask = {
  task_id: string;
  rules_hash: string;
  client_token: string;
  invite_token: string;
};

export type Verdict = {
  task_id: string;
  approved: boolean;
  reason: string;
  transaction_hash: string | null;
  /** v1: deterministic | llm | cache. Por ejecución (fase 3): hygiene | build | static | tests | judge | final. */
  stage: string;
  analysis: string[];
  comparison: string[];
  code_hash: string;
  verdict_hash: string;
  security_flags: string[];
  /** Enlace de Drive normalizado (…/preview) que entró al verdict_hash, o null. */
  video_url: string | null;
  submissions_used: number;
  /** Fase 3: detalle de la verificación por ejecución (en el perfil web, las capturas). */
  verification?: { profile?: string; screenshots?: Screenshot[] };
};

export type ClientVerdict = Pick<
  Verdict,
  "code_hash" | "approved" | "stage" | "reason" | "comparison" | "security_flags" | "transaction_hash"
> & { video_url?: string | null; consented?: boolean; screenshots?: Screenshot[] };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!API_URL) {
    throw new ApiError(0, "NOT_CONFIGURED", "Falta NEXT_PUBLIC_API_URL: el frontend no sabe dónde está el backend.");
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "NETWORK", `No se pudo conectar con el backend (${API_URL}).`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, body?.error ?? "HTTP_ERROR", body?.message ?? res.statusText);
  }
  return body as T;
}

export const api = {
  createProposal: (task_id: string, programador: string, clientToken: string, sessionToken: string) =>
    request<Proposal>("/propuestas", {
      method: "POST", headers: { "X-Client-Token": clientToken, Authorization: `Bearer ${sessionToken}` },
      body: JSON.stringify({ task_id, programador }),
    }),
  inbox: (sessionToken: string) => request<{ propuestas: InboxProposal[] }>("/buzon", {
    headers: { Authorization: `Bearer ${sessionToken}` },
  }),
  taskProposals: (id: string, clientToken: string, sessionToken: string) =>
    request<{ propuestas: Proposal[] }>(`/tasks/${encodeURIComponent(id)}/propuestas`, {
      headers: { "X-Client-Token": clientToken, Authorization: `Bearer ${sessionToken}` },
    }),
  acceptProposal: (id: string, sessionToken: string) =>
    request<Proposal & { freelancer_token: string }>(`/propuestas/${encodeURIComponent(id)}/aceptar`, {
      method: "POST", headers: { Authorization: `Bearer ${sessionToken}` },
    }),
  rejectProposal: (id: string, sessionToken: string) =>
    request<Proposal>(`/propuestas/${encodeURIComponent(id)}/rechazar`, {
      method: "POST", headers: { Authorization: `Bearer ${sessionToken}` },
    }),
  fx: () => request<Fx>("/fx/usd-mxn"),
  programmers: () => request<{ programmers: ProgrammerSummary[] }>("/programadores"),
  programmer: (address: string) => request<ProgrammerProfile>(`/programadores/${encodeURIComponent(address)}`),
  rateTask: (id: string, clientToken: string, estrellas: number, comentario: string | null, sessionToken: string) =>
    request<{ task_id: string } & Rating>(`/tasks/${encodeURIComponent(id)}/calificacion`, {
      method: "POST", headers: { "X-Client-Token": clientToken, Authorization: `Bearer ${sessionToken}` },
      body: JSON.stringify({ estrellas, comentario }),
    }),
  authChallenge: (address: string) => request<Challenge>(`/auth/challenge?address=${encodeURIComponent(address)}`),
  authToken: (transaction: string) =>
    request<{ token: string; address: string; expires_at: number }>("/auth/token", {
      method: "POST", body: JSON.stringify({ transaction }),
    }),
  putProfile: (sessionToken: string, profile: ProfileFields) =>
    request<{ address: string } & ProfileFields>("/perfil", {
      method: "PUT", headers: { Authorization: `Bearer ${sessionToken}` }, body: JSON.stringify(profile),
    }),
  consent: (id: string, token: string, code_hash: string) =>
    request<{ consented: boolean; code_hash: string }>(`/tasks/${encodeURIComponent(id)}/consent`, {
      method: "POST", headers: { "X-Freelancer-Token": token }, body: JSON.stringify({ code_hash }),
    }),
  // `profile: "web"` (verificador, perfil web): criterios que se comprueban en un navegador.
  draft: (raw_request: string, profile?: "web") =>
    request<Spec>("/tasks/draft", { method: "POST", body: JSON.stringify(profile ? { raw_request, profile } : { raw_request }) }),
  reviewDraft: (criteria: string[], profile?: "web") =>
    request<{ criteria: CriterionReview[] }>("/tasks/draft/review", {
      method: "POST", body: JSON.stringify(profile ? { criteria, profile } : { criteria }),
    }),
  demo: () => request<Demo>("/demo"),
  task: (id: string) => request<TaskView>(`/tasks/${encodeURIComponent(id)}`),
  createTask: (body: Record<string, unknown>) =>
    request<CreatedTask>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  accept: (id: string, freelancer_address: string, invite_token: string) =>
    request<{ freelancer_token: string }>(`/tasks/${encodeURIComponent(id)}/accept`, {
      method: "POST",
      body: JSON.stringify({ freelancer_address, invite_token }),
    }),
  evaluate: (task_id: string, freelancer_address: string, code: string, token: string, video_url: string | null = null) =>
    request<Verdict>("/evaluate", {
      method: "POST",
      headers: { "X-Freelancer-Token": token },
      body: JSON.stringify({ task_id, freelancer_address, code, video_url }),
    }),
  verify: (id: string, freelancer_address: string, source: VerificationSource, token: string, video_url: string | null = null) =>
    request<{ verification_id: string; status: string; submissions_used: number }>(
      `/tasks/${encodeURIComponent(id)}/verificaciones`,
      { method: "POST", headers: { "X-Freelancer-Token": token }, body: JSON.stringify({ freelancer_address, source, video_url }) },
    ),
  verification: (verificationId: string, headers: { freelancer?: string; client?: string }) =>
    request<VerificationStatus>(`/verificaciones/${encodeURIComponent(verificationId)}`, {
      headers: {
        ...(headers.freelancer ? { "X-Freelancer-Token": headers.freelancer } : {}),
        ...(headers.client ? { "X-Client-Token": headers.client } : {}),
      },
    }),
  retrySuite: (id: string, clientToken: string) =>
    request<SuitePlan & { task_id: string }>(`/tasks/${encodeURIComponent(id)}/suite/reintentar`, {
      method: "POST", headers: { "X-Client-Token": clientToken },
    }),
  delivery: (id: string, clientToken: string) =>
    request<{ code: string; video_url: string | null; code_hash: string }>(
      `/tasks/${encodeURIComponent(id)}/delivery`,
      { headers: { "X-Client-Token": clientToken } },
    ),
  verdicts: (id: string, clientToken: string) =>
    request<{ submissions_used: number; verdicts: ClientVerdict[] }>(
      `/tasks/${encodeURIComponent(id)}/verdicts`,
      { headers: { "X-Client-Token": clientToken } },
    ),
};
