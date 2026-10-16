/** EvalAI typed API client — every backend call funnels through `apiFetch`
 * so auth headers, error handling and base URL stay in one place. */
import { currentSession } from "@/lib/auth";

const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit & { upload?: boolean } = {}): Promise<T> {
  const { apiHeaders, upload, ...rest } = options as RequestInit & { apiHeaders?: HeadersInit; upload?: boolean };
  const headers = new Headers(apiHeaders);
  if (rest.body && !upload && !(rest.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // Identity comes from the verified Supabase session — never from payloads.
  const session = await currentSession().catch(() => null);
  if (session?.access_token) headers.set("Authorization", `Bearer ${session.access_token}`);

  const response = await fetch(`${API_BASE}${path}`, { ...rest, headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Fetch a binary artifact (e.g. an original submission PDF) with auth
 * headers and hand back a short-lived local object URL for <iframe>/<img>. */
export async function apiFetchObjectUrl(path: string): Promise<string> {
  const headers = new Headers();
  const session = await currentSession().catch(() => null);
  if (session?.access_token) headers.set("Authorization", `Bearer ${session.access_token}`);
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

// ---------------------------------------------------------------------------
// Shared API model types
// ---------------------------------------------------------------------------

export interface ProfileResponse {
  id: string;
  email: string;
  full_name: string;
  institution_id: string | null;
  role: string;
  department_ids: string[];
  subjects: string[];
}

export interface MeResponse {
  profile: ProfileResponse;
  user_id: string;
}
