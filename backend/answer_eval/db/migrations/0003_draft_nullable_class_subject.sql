-- EvalAI — Milestone 3: drafts may be created before class/subject selection
-- (Configure uploads the ZIP and answer key first; class/subject arrive at
-- step 3 and are required again before an assessment can be finalized).

alter table public.assessments alter column class_id drop not null;
alter table public.assessments alter column subject_id drop not null;
