/** Auth/profile API calls (backend mirrors identity from the verified JWT). */
import { apiFetch, type MeResponse, type ProfileResponse } from "./client";

export function fetchMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me");
}

export interface SyncProfilePayload {
  full_name?: string;
  department_ids?: string[];
  subjects?: string[];
}

export function syncProfile(payload: SyncProfilePayload): Promise<ProfileResponse> {
  return apiFetch<ProfileResponse>("/auth/sync-profile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProfile(payload: SyncProfilePayload): Promise<ProfileResponse> {
  return apiFetch<ProfileResponse>("/profile", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
