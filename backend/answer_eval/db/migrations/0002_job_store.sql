-- Milestone 14: durable JobStore backing (spec #69/#70).
-- Job existence/state/results live in Postgres — never only in Redis.
-- These tables back the JobStore protocol (jobs/pg_store.py);
-- evaluation_jobs/question_jobs remain the assessment-facing pipeline records.

create table if not exists public.job_records (
  job_id           text primary key,
  submission_id    text not null,
  status           text not null,
  attempt          integer not null default 1,
  worker_id        text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  lease_expires_at timestamptz,
  next_attempt_at  timestamptz,
  payload          jsonb not null
);

create index if not exists idx_job_records_claim
  on public.job_records (status, created_at);
create index if not exists idx_job_records_submission
  on public.job_records (submission_id);

create table if not exists public.job_results (
  submission_id text primary key,
  payload       jsonb not null,
  updated_at    timestamptz not null default now()
);

create table if not exists public.job_record_events (
  id         bigserial primary key,
  job_id     text not null,
  event      text not null,
  metadata   jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists idx_job_record_events_job
  on public.job_record_events (job_id, created_at);
