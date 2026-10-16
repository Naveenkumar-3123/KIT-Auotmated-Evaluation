-- EvalAI — Row Level Security (Milestone 1)
-- Model:
--   * The FastAPI backend connects with the service-role credential and derives
--     identity from verified Supabase JWTs; RLS is defense-in-depth for any
--     direct anon/authenticated access from the frontend.
--   * Teacher-owned rows are visible to the owning teacher and (read-only) to
--     colleagues of the same institution who share the assessment's class.
--   * Infrastructure tables (jobs, workers, audit, heartbeats) have no policies
--     => denied to everyone except service role / security-definer helpers.

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

create or replace function public.current_teacher_id() returns uuid
language sql stable security definer set search_path = public as $$
  select p.id from public.profiles p where p.id = auth.uid()
$$;

create or replace function public.is_authenticated_teacher() returns boolean
language sql stable security definer set search_path = public as $$
  select exists(select 1 from public.profiles p where p.id = auth.uid())
$$;

-- Owner OR same-institution colleague sharing the class (read path).
create or replace function public.can_access_assessment(p_assessment uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1
    from public.assessments a
    join public.profiles me on me.id = auth.uid()
    left join public.teacher_classes tc_mine
      on tc_mine.class_id = a.class_id and tc_mine.teacher_id = me.id
    where a.id = p_assessment
      and (
        a.teacher_id = me.id
        or (
          me.institution_id is not null
          and a.teacher_id in (
            select col.id from public.profiles col
            where col.institution_id = me.institution_id and col.id <> me.id
          )
          and exists (
            select 1 from public.teacher_classes tc_col
            where tc_col.class_id = a.class_id
              and tc_col.teacher_id in (
                select c2.id from public.profiles c2 where c2.institution_id = me.institution_id
              )
          )
        )
      )
  )
$$;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere
-- ---------------------------------------------------------------------------

alter table public.profiles                 enable row level security;
alter table public.institutions             enable row level security;
alter table public.classes                  enable row level security;
alter table public.subjects                 enable row level security;
alter table public.teacher_classes          enable row level security;
alter table public.teacher_subjects         enable row level security;
alter table public.assessments              enable row level security;
alter table public.assessment_students      enable row level security;
alter table public.answer_keys              enable row level security;
alter table public.questions                enable row level security;
alter table public.question_answer_keys     enable row level security;
alter table public.expected_concepts        enable row level security;
alter table public.keywords                 enable row level security;
alter table public.mandatory_terms          enable row level security;
alter table public.diagram_requirements     enable row level security;
alter table public.answer_key_diagrams      enable row level security;
alter table public.strictness_policies      enable row level security;
alter table public.word_count_policies      enable row level security;
alter table public.diagram_policies         enable row level security;
alter table public.question_policies        enable row level security;
alter table public.submissions              enable row level security;
alter table public.submission_files         enable row level security;
alter table public.submission_pages         enable row level security;
alter table public.question_spans           enable row level security;
alter table public.question_regions         enable row level security;
alter table public.ocr_results              enable row level security;
alter table public.reconstructed_answers    enable row level security;
alter table public.student_diagrams         enable row level security;
alter table public.evaluation_jobs          enable row level security;
alter table public.question_jobs            enable row level security;
alter table public.job_events               enable row level security;
alter table public.evaluation_results       enable row level security;
alter table public.criterion_scores         enable row level security;
alter table public.verification_results     enable row level security;
alter table public.verification_comparisons enable row level security;
alter table public.risk_results             enable row level security;
alter table public.teacher_reviews          enable row level security;
alter table public.teacher_overrides        enable row level security;
alter table public.final_results            enable row level security;
alter table public.student_totals           enable row level security;
alter table public.worker_nodes             enable row level security;
alter table public.worker_heartbeats        enable row level security;
alter table public.audit_events             enable row level security;

-- ---------------------------------------------------------------------------
-- Profiles: own row only
-- ---------------------------------------------------------------------------

create policy profiles_select_own on public.profiles
  for select using (id = auth.uid());
create policy profiles_insert_self on public.profiles
  for insert with check (id = auth.uid());
create policy profiles_update_own on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- ---------------------------------------------------------------------------
-- Catalogs: institution-scoped read + creator manage
-- ---------------------------------------------------------------------------

create policy institutions_read_member on public.institutions
  for select using (
    id in (select institution_id from public.profiles where id = auth.uid())
  );
create policy institutions_insert_member on public.institutions
  for insert with check (is_authenticated_teacher());

create policy classes_read on public.classes for select using (
  created_by = auth.uid()
  or (institution_id is not null and institution_id in
      (select institution_id from public.profiles where id = auth.uid()))
);
create policy classes_write_creator on public.classes
  for insert with check (created_by = auth.uid());
create policy classes_update_creator on public.classes
  for update using (created_by = auth.uid()) with check (created_by = auth.uid());

create policy subjects_read on public.subjects for select using (
  created_by = auth.uid()
  or (institution_id is not null and institution_id in
      (select institution_id from public.profiles where id = auth.uid()))
);
create policy subjects_write_creator on public.subjects
  for insert with check (created_by = auth.uid());
create policy subjects_update_creator on public.subjects
  for update using (created_by = auth.uid()) with check (created_by = auth.uid());

create policy teacher_classes_own on public.teacher_classes
  for all using (teacher_id = auth.uid()) with check (teacher_id = auth.uid());
create policy teacher_subjects_own on public.teacher_subjects
  for all using (teacher_id = auth.uid()) with check (teacher_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Assessments + everything hanging off them
-- ---------------------------------------------------------------------------

create policy assessments_select_access on public.assessments
  for select using (public.can_access_assessment(id));
create policy assessments_insert_own on public.assessments
  for insert with check (teacher_id = auth.uid());
create policy assessments_update_owner on public.assessments
  for update using (teacher_id = auth.uid()) with check (teacher_id = auth.uid());
create policy assessments_delete_owner on public.assessments
  for delete using (teacher_id = auth.uid());

-- Generic child-of-assessment policies (service-role backend also passes these).
create policy students_via_assessment on public.assessment_students
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy answer_keys_via_assessment on public.answer_keys
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy questions_via_key on public.questions
  for all using (
    exists (select 1 from public.answer_keys k
            where k.id = answer_key_id and public.can_access_assessment(k.assessment_id))
  ) with check (
    exists (select 1 from public.answer_keys k
            where k.id = answer_key_id and public.can_access_assessment(k.assessment_id))
  );

create policy qak_via_assessment on public.question_answer_keys
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

-- Question-detail children resolve through questions -> answer_keys -> assessment.
create policy concepts_via_question on public.expected_concepts
  for all using (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  ) with check (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  );

create policy keywords_via_question on public.keywords
  for all using (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  ) with check (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  );

create policy mandatory_via_question on public.mandatory_terms
  for all using (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  ) with check (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  );

create policy diagreq_via_question on public.diagram_requirements
  for all using (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  ) with check (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  );

create policy keydiag_via_question on public.answer_key_diagrams
  for all using (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  ) with check (
    exists (select 1 from public.questions q join public.answer_keys k on k.id = q.answer_key_id
            where q.id = question_id and public.can_access_assessment(k.assessment_id))
  );

create policy strictness_via_assessment on public.strictness_policies
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));
create policy wordcount_via_assessment on public.word_count_policies
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));
create policy diagpol_via_assessment on public.diagram_policies
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));
create policy resolved_via_assessment on public.question_policies
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy submissions_via_assessment on public.submissions
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy subfiles_via_submission on public.submission_files
  for all using (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  );

create policy pages_via_submission on public.submission_pages
  for all using (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  );

create policy spans_via_submission on public.question_spans
  for all using (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  );

create policy regions_via_submission on public.question_regions
  for all using (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  );

create policy ocr_via_region on public.ocr_results
  for all using (
    exists (select 1 from public.question_regions r join public.submissions s on s.id = r.submission_id
            where r.id = region_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.question_regions r join public.submissions s on s.id = r.submission_id
            where r.id = region_id and public.can_access_assessment(s.assessment_id))
  );

create policy recon_via_submission on public.reconstructed_answers
  for all using (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  );

create policy stdiag_via_submission on public.student_diagrams
  for all using (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  ) with check (
    exists (select 1 from public.submissions s
            where s.id = submission_id and public.can_access_assessment(s.assessment_id))
  );

create policy results_via_assessment on public.evaluation_results
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy criterion_via_result on public.criterion_scores
  for all using (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  ) with check (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  );

create policy verif_via_result on public.verification_results
  for all using (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  ) with check (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  );

create policy comp_via_result on public.verification_comparisons
  for all using (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  ) with check (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  );

create policy risk_via_result on public.risk_results
  for all using (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  ) with check (
    exists (select 1 from public.evaluation_results er
            where er.id = result_id and public.can_access_assessment(er.assessment_id))
  );

create policy reviews_via_assessment on public.teacher_reviews
  for select using (public.can_access_assessment(assessment_id));
create policy reviews_insert_system on public.teacher_reviews
  for insert with check (public.can_access_assessment(assessment_id));
create policy reviews_update_reviewer on public.teacher_reviews
  for update using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy overrides_via_review on public.teacher_overrides
  for all using (
    exists (select 1 from public.teacher_reviews tr
            where tr.id = review_id and public.can_access_assessment(tr.assessment_id))
  ) with check (
    exists (select 1 from public.teacher_reviews tr
            where tr.id = review_id and public.can_access_assessment(tr.assessment_id))
  );

create policy finals_via_assessment on public.final_results
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

create policy totals_via_assessment on public.student_totals
  for all using (public.can_access_assessment(assessment_id))
  with check (public.can_access_assessment(assessment_id));

-- ---------------------------------------------------------------------------
-- Infrastructure tables: NO policies => only service_role may touch them.
-- (evaluation_jobs, question_jobs, job_events, worker_nodes,
--  worker_heartbeats, audit_events)
-- ---------------------------------------------------------------------------
