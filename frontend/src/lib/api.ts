// Cliente del backend de Cumple&Cobra. El frontend nunca toca llaves ni la API de Gemini.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Example = { input: string; output: string };
export type Fx = { rate: string; as_of: string; source: string; fallback: boolean };
export type CriterionReview = { index: number; vague: boolean; suggestion: string | null };

export type Spec = {
  description: string;
  criteria: string[];
  language: string;
  allowed_deps: string[];
  examples: Example[];
};

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
};

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
  stage: "deterministic" | "llm" | "cache";
  analysis: string[];
  comparison: string[];
  code_hash: string;
  verdict_hash: string;
  security_flags: string[];
  /** Enlace de Drive normalizado (…/preview) que entró al verdict_hash, o null. */
  video_url: string | null;
  submissions_used: number;
};

export type ClientVerdict = Pick<
  Verdict,
  "code_hash" | "approved" | "stage" | "reason" | "comparison" | "security_flags" | "transaction_hash"
> & { video_url?: string | null; consented?: boolean };

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
  fx: () => request<Fx>("/fx/usd-mxn"),
  programmers: () => request<{ programmers: ProgrammerSummary[] }>("/programadores"),
  programmer: (address: string) => request<ProgrammerProfile>(`/programadores/${encodeURIComponent(address)}`),
  rateTask: (id: string, clientToken: string, estrellas: number, comentario: string | null) =>
    request<{ task_id: string } & Rating>(`/tasks/${encodeURIComponent(id)}/calificacion`, {
      method: "POST", headers: { "X-Client-Token": clientToken }, body: JSON.stringify({ estrellas, comentario }),
    }),
  consent: (id: string, token: string, code_hash: string) =>
    request<{ consented: boolean; code_hash: string }>(`/tasks/${encodeURIComponent(id)}/consent`, {
      method: "POST", headers: { "X-Freelancer-Token": token }, body: JSON.stringify({ code_hash }),
    }),
  draft: (raw_request: string) =>
    request<Spec>("/tasks/draft", { method: "POST", body: JSON.stringify({ raw_request }) }),
  reviewDraft: (criteria: string[]) =>
    request<{ criteria: CriterionReview[] }>("/tasks/draft/review", {
      method: "POST", body: JSON.stringify({ criteria }),
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
