-- EvalAI — initial schema (Milestone 1)
-- Conventions: uuid PKs (gen_random_uuid), timestamptz created_at/updated_at,
-- integer `version` where rows are versioned, TEXT+CHECK for status enums
-- (simpler evolution than native enums). All teacher-owned rows trace to
-- profiles.id which references auth.users.id.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------------

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Identity / institutions / catalogs
-- ---------------------------------------------------------------------------

create table public.institutions (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table public.profiles (
  id              uuid primary key references auth.users(id) on delete cascade,
  email           text not null unique,
  full_name       text not null default '',
  institution_id  uuid references public.institutions(id) on delete set null,
  role            text not null default 'teacher' check (role in ('teacher','admin')),
  department_ids  jsonb not null default '[]',
  subjects        jsonb not null default '[]',
  settings        jsonb not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.classes (
  id              uuid primary key default gen_random_uuid(),
  institution_id  uuid references public.institutions(id) on delete cascade,
  created_by      uuid not null references public.profiles(id) on delete cascade,
  name            text not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (institution_id, name)
);

create table public.subjects (
  id              uuid primary key default gen_random_uuid(),
  institution_id  uuid references public.institutions(id) on delete cascade,
  created_by      uuid not null references public.profiles(id) on delete cascade,
  name            text not null,
  code            text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.teacher_classes (
  teacher_id  uuid not null references public.profiles(id) on delete cascade,
  class_id    uuid not null references public.classes(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (teacher_id, class_id)
);

create table public.teacher_subjects (
  teacher_id  uuid not null references public.profiles(id) on delete cascade,
  subject_id  uuid not null references public.subjects(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (teacher_id, subject_id)
);

-- ---------------------------------------------------------------------------
-- Assessments
-- ---------------------------------------------------------------------------

create table public.assessments (
  id                        uuid primary key default gen_random_uuid(),
  teacher_id                uuid not null references public.profiles(id) on delete cascade,
  class_id                  uuid not null references public.classes(id),
  subject_id                uuid not null references public.subjects(id),
  title                     text not null default 'Untitled assessment',
  status                    text not null default 'draft'
                            check (status in ('draft','configured','processing','waiting_for_review','completed','failed','archived')),
  pass_percentage           numeric(5,2) not null default 40 check (pass_percentage >= 0 and pass_percentage <= 100),
  total_marks               numeric(8,2) not null default 0,
  question_count            integer not null default 0,
  locked_answer_key_version integer,
  locked_policy_version     integer,
  rubric_version            text,
  started_at                timestamptz,
  completed_at              timestamptz,
  version                   integer not null default 1,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);
create index idx_assessments_teacher on public.assessments(teacher_id, created_at desc);

create table public.assessment_students (
  id              uuid primary key default gen_random_uuid(),
  assessment_id   uuid not null references public.assessments(id) on delete cascade,
  roll_number     text not null,
  display_name    text,
  status          text not null default 'pending'
                  check (status in ('pending','queued','processing','waiting_for_review','completed','failed','invalid')),
  status_detail   text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (assessment_id, roll_number)
);

-- ---------------------------------------------------------------------------
-- Answer keys + parsed question content
-- ---------------------------------------------------------------------------

create table public.answer_keys (
  id                    uuid primary key default gen_random_uuid(),
  assessment_id         uuid not null references public.assessments(id) on delete cascade,
  version               integer not null default 1,
  source_object_key     text not null,
  source_format         text not null check (source_format in ('pdf','doc','docx','jpg','jpeg','png','webp')),
  source_sha256         char(64),
  raw_parser_json       jsonb,
  parser_model          text,
  parser_prompt_version text,
  schema_version        text not null default 'answer-key-v1',
  status                text not null default 'parsed' check (status in ('parsing','parsed','reviewed','locked','failed')),
  parse_error           text,
  created_by            uuid not null references public.profiles(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (assessment_id, version)
);
create index idx_answer_keys_assessment on public.answer_keys(assessment_id, version desc);

create table public.questions (
  id                   uuid primary key default gen_random_uuid(),
  answer_key_id        uuid not null references public.answer_keys(id) on delete cascade,
  question_number      integer not null,
  ordinal              integer,
  question_text        text not null default '',
  maximum_marks        numeric(6,2) not null,
  answer_type          text not null default 'descriptive'
                       check (answer_type in ('descriptive','explain','numerical','formula','diagram','mixed','short_answer','unsupported')),
  expected_answer_text text not null default '',
  math_rubric          jsonb,
  parser_uncertainties jsonb not null default '[]',
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (answer_key_id, question_number)
);

-- Which question rows of the locked key version are active for an assessment.
create table public.question_answer_keys (
  id             uuid primary key default gen_random_uuid(),
  assessment_id  uuid not null references public.assessments(id) on delete cascade,
  question_id    uuid not null references public.questions(id) on delete cascade,
  active         boolean not null default true,
  created_at     timestamptz not null default now(),
  unique (assessment_id, question_id)
);

create table public.expected_concepts (
  id             uuid primary key default gen_random_uuid(),
  question_id    uuid not null references public.questions(id) on delete cascade,
  concept_code   text not null,
  description    text not null default '',
  maximum_marks  numeric(6,2) not null default 0 check (maximum_marks >= 0),
  ordinal        integer not null default 0,
  created_at     timestamptz not null default now(),
  unique (question_id, concept_code)
);

create table public.keywords (
  id           uuid primary key default gen_random_uuid(),
  question_id  uuid not null references public.questions(id) on delete cascade,
  term         text not null,
  weight       numeric(4,2) not null default 1,
  created_at   timestamptz not null default now(),
  unique (question_id, term)
);

create table public.mandatory_terms (
  id           uuid primary key default gen_random_uuid(),
  question_id  uuid not null references public.questions(id) on delete cascade,
  term         text not null,
  created_at   timestamptz not null default now(),
  unique (question_id, term)
);

-- Rubric-level diagram expectations extracted from the answer key.
create table public.diagram_requirements (
  id                  uuid primary key default gen_random_uuid(),
  question_id         uuid not null references public.questions(id) on delete cascade,
  required            boolean not null default false,
  count_required      integer not null default 0,
  required_labels     jsonb not null default '[]',
  required_components jsonb not null default '[]',
  notes               text,
  created_at          timestamptz not null default now()
);

-- ORIGINAL answer-key diagram crops (primary evidence; descriptions auxiliary).
create table public.answer_key_diagrams (
  id                 uuid primary key default gen_random_uuid(),
  question_id        uuid not null references public.questions(id) on delete cascade,
  diagram_code       text not null,
  ordinal            integer not null default 1,
  type_label         text,
  image_object_key   text not null,
  source_page        integer,
  bbox               jsonb,
  parser_uncertain   boolean not null default false,
  created_at         timestamptz not null default now(),
  unique (question_id, ordinal)
);

-- ---------------------------------------------------------------------------
-- Policies (teacher rules; ranges or per-question)
-- ---------------------------------------------------------------------------

create table public.strictness_policies (
  id              uuid primary key default gen_random_uuid(),
  assessment_id   uuid not null references public.assessments(id) on delete cascade,
  scope_type      text not null default 'all' check (scope_type in ('all','range','question')),
  question_from   integer,
  question_to     integer,
  question_number integer,
  level           text not null check (level in ('lenient','moderate','strict')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.word_count_policies (
  id                      uuid primary key default gen_random_uuid(),
  assessment_id           uuid not null references public.assessments(id) on delete cascade,
  scope_type              text not null default 'all' check (scope_type in ('all','range','question')),
  question_from           integer,
  question_to             integer,
  question_number         integer,
  minimum_words           integer not null default 0 check (minimum_words >= 0),
  mode                    text not null default 'once' check (mode in ('once','per_step')),
  trigger_shortfall_words integer not null default 0 check (trigger_shortfall_words >= 0),
  marks_deducted          numeric(6,2) not null default 0 check (marks_deducted >= 0),
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create table public.diagram_policies (
  id                         uuid primary key default gen_random_uuid(),
  assessment_id              uuid not null references public.assessments(id) on delete cascade,
  scope_type                 text not null default 'all' check (scope_type in ('all','range','question')),
  question_from              integer,
  question_to                integer,
  question_number            integer,
  required                   boolean not null default false,
  minimum_diagrams           integer not null default 1 check (minimum_diagrams >= 1),
  missing_diagram_deductions jsonb not null default '[]',
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now()
);

-- RESOLVED per-question policy snapshot. Immutable once assessments.started_at
-- is set: evaluation reads this table, never the editable rule tables above.
create table public.question_policies (
  id                         uuid primary key default gen_random_uuid(),
  assessment_id              uuid not null references public.assessments(id) on delete cascade,
  version                    integer not null default 1,
  question_number            integer not null,
  strictness_level           text not null check (strictness_level in ('lenient','moderate','strict')),
  minimum_words              integer not null default 0,
  word_count_mode            text not null default 'once',
  trigger_shortfall_words    integer not null default 0,
  marks_deducted             numeric(6,2) not null default 0,
  diagram_required           boolean not null default false,
  min_diagrams               integer not null default 0,
  missing_diagram_deductions jsonb not null default '[]',
  source_rule_ids            jsonb not null default '[]',
  rubric_snapshot            jsonb,
  created_at                 timestamptz not null default now(),
  unique (assessment_id, version, question_number)
);

-- ---------------------------------------------------------------------------
-- Ingestion / perception artifacts
-- ---------------------------------------------------------------------------

create table public.submissions (
  id              uuid primary key default gen_random_uuid(),
  assessment_id   uuid not null references public.assessments(id) on delete cascade,
  roll_number     text not null,
  student_label   text,
  status          text not null default 'uploaded'
                  check (status in ('uploaded','invalid','queued','processing','evaluating','waiting_for_review','completed','failed')),
  status_detail   text,
  pdf_object_key  text not null,
  pdf_sha256      char(64),
  page_count      integer,
  flags           jsonb not null default '[]',
  uploaded_by     uuid references public.profiles(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (assessment_id, roll_number)
);
create index idx_submissions_assessment on public.submissions(assessment_id, status);
create unique index uq_submissions_pdf_hash on public.submissions(assessment_id, pdf_sha256) where pdf_sha256 is not null;

create table public.submission_files (
  id             uuid primary key default gen_random_uuid(),
  submission_id  uuid not null references public.submissions(id) on delete cascade,
  kind           text not null check (kind in ('zip_entry','original_pdf','rendered_page','crop','artifact')),
  object_key     text not null,
  sha256         char(64),
  size_bytes     bigint,
  content_type   text,
  created_at     timestamptz not null default now()
);

create table public.submission_pages (
  id                 uuid primary key default gen_random_uuid(),
  submission_id      uuid not null references public.submissions(id) on delete cascade,
  page_number        integer not null check (page_number >= 1),
  image_object_key   text,
  original_object_key text,
  width_px           integer,
  height_px          integer,
  quality_metrics    jsonb,
  created_at         timestamptz not null default now(),
  unique (submission_id, page_number)
);

-- Cross-page mapping output (QuestionSpanMapper).
create table public.question_spans (
  id                  uuid primary key default gen_random_uuid(),
  submission_id       uuid not null references public.submissions(id) on delete cascade,
  question_id         text not null,
  start_page          integer not null,
  end_page            integer not null,
  region_ids          jsonb not null default '[]',
  diagram_region_ids  jsonb not null default '[]',
  mapping_uncertain   boolean not null default false,
  uncertainty_reasons jsonb not null default '[]',
  mapper_version      text not null default 'span-mapper-v1',
  created_at          timestamptz not null default now(),
  unique (submission_id, question_id)
);

create table public.question_regions (
  id              uuid primary key default gen_random_uuid(),
  span_id         uuid references public.question_spans(id) on delete cascade,
  submission_id   uuid not null references public.submissions(id) on delete cascade,
  page_number     integer not null,
  bbox            jsonb not null,
  region_type     text not null check (region_type in ('answer_text','diagram','mixed','blank','margin_note')),
  reading_order   integer not null default 0,
  crop_object_key text,
  confidence      numeric(5,4),
  created_at      timestamptz not null default now()
);
create index idx_regions_submission on public.question_regions(submission_id, page_number, reading_order);

create table public.ocr_results (
  id              uuid primary key default gen_random_uuid(),
  region_id       uuid not null references public.question_regions(id) on delete cascade,
  raw_text        text not null default '',
  lines           jsonb not null default '[]',
  uncertain_spans jsonb not null default '[]',
  flags           jsonb not null default '[]',
  word_count      integer not null default 0,
  model_id        text,
  prompt_version  text,
  status          text not null default 'success' check (status in ('success','truncated','empty_response','failed')),
  created_at      timestamptz not null default now()
);

create table public.reconstructed_answers (
  id                uuid primary key default gen_random_uuid(),
  submission_id     uuid not null references public.submissions(id) on delete cascade,
  question_id       text not null,
  raw_text          text not null default '',
  normalized_text   text,
  word_count        integer not null default 0,
  segments          jsonb not null default '[]',
  packet_object_key text,
  uncertainties     jsonb not null default '[]',
  flags             jsonb not null default '[]',
  provenance        jsonb not null default '{}',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (submission_id, question_id)
);

create table public.student_diagrams (
  id               uuid primary key default gen_random_uuid(),
  submission_id    uuid not null references public.submissions(id) on delete cascade,
  question_id      text not null,
  diagram_code     text not null,
  ordinal          integer not null default 1,
  image_object_key text not null,
  page             integer,
  bbox             jsonb,
  extracted_by     text,
  metadata         jsonb not null default '{}',
  uncertain        boolean not null default false,
  created_at       timestamptz not null default now(),
  unique (submission_id, question_id, ordinal)
);

-- ---------------------------------------------------------------------------
-- Jobs (durable truth; Redis holds only queue/lease caches)
-- ---------------------------------------------------------------------------

create table public.evaluation_jobs (
  id                 uuid primary key default gen_random_uuid(),
  assessment_id      uuid not null references public.assessments(id) on delete cascade,
  submission_id      uuid not null references public.submissions(id) on delete cascade,
  job_kind           text not null default 'submission_pipeline',
  status             text not null default 'queued'
                     check (status in ('queued','claimed','processing','waiting_for_review','retrying','completed','failed','cancelled')),
  attempt            integer not null default 0,
  max_attempts       integer not null default 3,
  input_hash         char(64),
  lease_owner        text,
  lease_expires_at   timestamptz,
  current_stage      text,
  progress           numeric(5,2) not null default 0,
  failure            jsonb,
  assignment_history jsonb not null default '[]',
  result_id          uuid,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index idx_jobs_lease on public.evaluation_jobs(status, lease_expires_at);
create unique index uq_jobs_input_hash on public.evaluation_jobs(input_hash) where input_hash is not null;

-- Atomic grading unit: ONE student x ONE whole question (all its pages).
create table public.question_jobs (
  id                 uuid primary key default gen_random_uuid(),
  assessment_id      uuid not null references public.assessments(id) on delete cascade,
  submission_id      uuid not null references public.submissions(id) on delete cascade,
  question_id        text not null,
  span_id            uuid references public.question_spans(id) on delete set null,
  status             text not null default 'queued'
                     check (status in ('queued','claimed','processing','waiting_for_review','retrying','completed','failed','cancelled')),
  attempt            integer not null default 0,
  max_attempts       integer not null default 3,
  input_hash         char(64),
  lease_owner        text,
  lease_expires_at   timestamptz,
  stage              text,
  failure            jsonb,
  assignment_history jsonb not null default '[]',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (submission_id, question_id)
);
create index idx_qjobs_lease on public.question_jobs(status, lease_expires_at);
create unique index uq_qjobs_input_hash on public.question_jobs(input_hash) where input_hash is not null;

create table public.job_events (
  id         bigserial primary key,
  job_type   text not null check (job_type in ('submission_pipeline','question_evaluation')),
  job_id     uuid not null,
  event      text not null,
  payload    jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index idx_job_events_job on public.job_events(job_type, job_id, id);

-- ---------------------------------------------------------------------------
-- Results / verification / review
-- ---------------------------------------------------------------------------

create table public.evaluation_results (
  id                  uuid primary key default gen_random_uuid(),
  question_job_id     uuid references public.question_jobs(id) on delete set null,
  assessment_id       uuid not null references public.assessments(id) on delete cascade,
  submission_id       uuid not null references public.submissions(id) on delete cascade,
  question_id         text not null,
  criteria            jsonb not null default '[]',
  proposed_marks      numeric(6,2) not null default 0,
  marks_maximum       numeric(6,2) not null default 0,
  breakdown           jsonb not null default '{}',
  evidence_issues     jsonb not null default '[]',
  model_id            text,
  model_profile       text,
  quantization        text,
  provider            text,
  prompt_version      text,
  answer_key_version  integer,
  policy_version      integer,
  schema_version      text not null default 'evaluation-result-v1',
  attempt             integer not null default 1,
  created_at          timestamptz not null default now()
);
create index idx_results_submission on public.evaluation_results(submission_id, question_id);

create table public.criterion_scores (
  id            uuid primary key default gen_random_uuid(),
  result_id     uuid not null references public.evaluation_results(id) on delete cascade,
  concept_code  text not null,
  awarded       numeric(6,2) not null default 0,
  maximum       numeric(6,2) not null default 0,
  status        text not null check (status in ('fully_supported','partially_supported','unsupported','contradicted','uncertain','not_applicable')),
  match_type    text,
  evidence      jsonb not null default '[]',
  comment       text,
  created_at    timestamptz not null default now()
);
create index idx_criterion_result on public.criterion_scores(result_id);

create table public.verification_results (
  id              uuid primary key default gen_random_uuid(),
  result_id       uuid not null references public.evaluation_results(id) on delete cascade,
  criteria        jsonb not null default '[]',
  proposed_marks  numeric(6,2) not null default 0,
  model_id        text,
  prompt_version  text,
  created_at      timestamptz not null default now()
);

create table public.verification_comparisons (
  id                 uuid primary key default gen_random_uuid(),
  result_id          uuid not null references public.evaluation_results(id) on delete cascade,
  comparison         jsonb not null default '{}',
  total_delta        numeric(6,2) not null default 0,
  agreement_rate     numeric(5,4),
  major_disagreement boolean not null default false,
  created_at         timestamptz not null default now()
);

create table public.risk_results (
  id               uuid primary key default gen_random_uuid(),
  result_id        uuid not null references public.evaluation_results(id) on delete cascade,
  risk_score       numeric(5,4) not null default 0,
  level            text not null check (level in ('low','medium','high')),
  signals          jsonb not null default '[]',
  mandatory_review boolean not null default false,
  reasons          jsonb not null default '[]',
  created_at       timestamptz not null default now()
);

create table public.teacher_reviews (
  id             uuid primary key default gen_random_uuid(),
  result_id      uuid references public.evaluation_results(id) on delete set null,
  assessment_id  uuid not null references public.assessments(id) on delete cascade,
  submission_id  uuid not null references public.submissions(id) on delete cascade,
  question_id    text not null,
  status         text not null default 'pending' check (status in ('pending','approved','overridden','requeued')),
  reasons        jsonb not null default '[]',
  reviewer_id    uuid references public.profiles(id),
  note           text,
  decided_at     timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index idx_reviews_open on public.teacher_reviews(assessment_id, status);

create table public.teacher_overrides (
  id          uuid primary key default gen_random_uuid(),
  review_id   uuid not null references public.teacher_reviews(id) on delete cascade,
  target      text not null check (target in ('criterion','final_marks','ocr_text','mapping','diagram_status')),
  target_key  text,
  old_value   jsonb,
  new_value   jsonb,
  reason      text,
  reviewer_id uuid not null references public.profiles(id),
  created_at  timestamptz not null default now()
);

-- Final immutable-ish outcome per student-question (latest row wins via upsert).
create table public.final_results (
  id             uuid primary key default gen_random_uuid(),
  submission_id  uuid not null references public.submissions(id) on delete cascade,
  assessment_id  uuid not null references public.assessments(id) on delete cascade,
  question_id    text not null,
  marks_awarded  numeric(6,2) not null default 0,
  marks_maximum  numeric(6,2) not null default 0,
  deductions     jsonb not null default '[]',
  breakdown      jsonb not null default '{}',
  source         text not null default 'ai' check (source in ('ai','review')),
  approved_by    uuid references public.profiles(id),
  result_id      uuid references public.evaluation_results(id) on delete set null,
  review_id      uuid references public.teacher_reviews(id) on delete set null,
  answer_key_version integer,
  policy_version     integer,
  version        integer not null default 1,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (submission_id, question_id)
);
create index idx_final_assessment on public.final_results(assessment_id);

create table public.student_totals (
  id             uuid primary key default gen_random_uuid(),
  submission_id  uuid not null unique references public.submissions(id) on delete cascade,
  assessment_id  uuid not null references public.assessments(id) on delete cascade,
  total          numeric(8,2) not null default 0,
  maximum        numeric(8,2) not null default 0,
  percentage     numeric(5,2) not null default 0,
  passed         boolean,
  rank           integer,
  status         text not null default 'in_progress' check (status in ('in_progress','finalized','failed')),
  version        integer not null default 1,
  computed_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Worker fleet
-- ---------------------------------------------------------------------------

create table public.worker_nodes (
  worker_id       text primary key,
  token_hash      text not null,
  hostname        text,
  hardware        jsonb not null default '{}',
  model_profile   text,
  capabilities    text[] not null default '{}',
  status          text not null default 'offline' check (status in ('online','busy','idle','unhealthy','offline')),
  current_job_id  uuid,
  registered_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

create table public.worker_heartbeats (
  id             bigserial primary key,
  worker_id      text not null references public.worker_nodes(worker_id) on delete cascade,
  stage          text,
  current_job_id uuid,
  ram_used_gb    numeric(8,2),
  vram_used_gb   numeric(8,2),
  progress       numeric(5,2),
  created_at     timestamptz not null default now()
);
create index idx_worker_hb on public.worker_heartbeats(worker_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------

create table public.audit_events (
  id          bigserial primary key,
  actor_id    uuid references public.profiles(id) on delete set null,
  action      text not null,
  entity_type text not null,
  entity_id   text,
  before      jsonb,
  after       jsonb,
  metadata    jsonb not null default '{}',
  created_at  timestamptz not null default now()
);
create index idx_audit_entity on public.audit_events(entity_type, entity_id, id desc);

-- ---------------------------------------------------------------------------
-- updated_at triggers
-- ---------------------------------------------------------------------------

do $$
declare t text;
begin
  foreach t in array array[
    'profiles','institutions','classes','subjects','assessments','assessment_students',
    'answer_keys','questions','submissions','reconstructed_answers',
    'strictness_policies','word_count_policies','diagram_policies',
    'teacher_reviews','final_results','student_totals'
  ] loop
    execute format('drop trigger if exists trg_touch_%1$s on public.%1$s', t);
    execute format(
      'create trigger trg_touch_%1$s before update on public.%1$s
       for each row execute function public.touch_updated_at()', t);
  end loop;
end $$;
