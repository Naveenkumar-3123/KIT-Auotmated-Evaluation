/** Worker fleet API (Milestone 16) — Computers page data. */
import { apiFetch } from "./client";

export interface WorkerFleetEntry {
  worker_id: string;
  hostname: string | null;
  hardware: { cpu?: string | null; ram_gb?: number | null; gpu?: string | null; vram_gb?: number | null };
  model_profile: string | null;
  capabilities: string[];
  current_job_id: string | null;
  online: boolean;
  last_seen_at: string | null;
  latest_beat_at: string | null;
  stage: string | null;
  progress: number | null;
  ram_used_gb: number | null;
  vram_used_gb: number | null;
  roll_number: string | null;
}

export interface WorkerFleetResponse {
  workers: WorkerFleetEntry[];
  online_count: number;
  total_count: number;
}

export function listWorkers(): Promise<WorkerFleetResponse> {
  return apiFetch<WorkerFleetResponse>("/workers");
}

