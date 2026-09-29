"""Results read-model (Milestone 17, specs #70/#73/#74).

Incremental by design: every submission contributes its real status; marks
come only from durable final_results — queued/processing students are never
mixed into averages as zeros (#79).
"""

from __future__ import annotations

from typing import Any

import asyncpg


async def assessment_results(pool: asyncpg.Pool, assessment_id: str) -> dict[str, Any]:
    meta = await pool.fetchrow(
        """select id, title, total_marks, pass_percentage, status, question_count
           from assessments where id = $1::uuid""",
        __import__("uuid").UUID(assessment_id),
    )
    rows = await pool.fetch(
        """
        select s.id as submission_id, s.roll_number, s.status,
               coalesce(sum(f.marks_awarded), 0) as total_awarded,
               coalesce(max(f.marks_maximum), 0) as maximum,
               bool_or(f.source = 'review') as teacher_modified,
               count(f.id) filter (where f.source = 'review') as review_resolved
        from submissions s
        left join final_results f on f.submission_id = s.id
        where s.assessment_id = $1::uuid
        group by s.id, s.roll_number, s.status
        order by s.roll_number
        """,
        __import__("uuid").UUID(assessment_id),
    )
    maximum = float(meta["total_marks"] or 0)
    pass_mark = float(meta["pass_percentage"] or 0)

    students: list[dict[str, Any]] = []
    for row in rows:
        total = round(float(row["total_awarded"]), 2)
        pct = round((total / maximum * 100.0), 2) if maximum > 0 else None
        students.append(
            {
                "submission_id": str(row["submission_id"]),
                "roll_number": row["roll_number"],
                "status": row["status"],
                "total": total,
                "maximum": maximum,
                "percentage": pct,
                "passed": (pct >= pass_mark) if pct is not None else None,
                "teacher_modified": bool(row["teacher_modified"]),
                "graded_questions": int(row["review_resolved"]),
                "rank": None,
                "highest": False,
            }
        )

    # Standard-competition ranking over completed students only (#79).
    completed_indices = [i for i, s in enumerate(students) if s["status"] == "completed"]
    sorted_indices = sorted(completed_indices, key=lambda i: students[i]["total"], reverse=True)
    sorted_totals = [students[i]["total"] for i in sorted_indices]
    for position, student_index in enumerate(sorted_indices, start=1):
        students[student_index]["rank"] = sorted_totals.index(students[student_index]["total"]) + 1
        if position == 1:
            students[student_index]["highest"] = True

    summary = {
        "total": len(students),
        "completed": sum(1 for s in students if s["status"] == "completed"),
        "waiting_for_review": sum(1 for s in students if s["status"] == "waiting_for_review"),
        "processing": sum(1 for s in students if s["status"] in ("queued", "processing", "evaluating")),
        "ready": sum(1 for s in students if s["status"] == "uploaded"),
        "failed": sum(1 for s in students if s["status"] in ("invalid", "failed")),
    }
    return {
        "assessment_id": assessment_id,
        "title": meta["title"],
        "status": meta["status"],
        "question_count": meta["question_count"],
        "total_marks": maximum,
        "pass_percentage": pass_mark,
        "summary": summary,
        "students": students,
    }


async def submission_results(pool: asyncpg.Pool, submission_id: str) -> dict[str, Any]:
    uid = __import__("uuid").UUID(submission_id)
    sub = await pool.fetchrow(
        "select id, assessment_id, roll_number, status from submissions where id = $1::uuid", uid
    )
    if sub is None:
        return {}
    strict_by_q: dict[str, str] = {}
    if sub["assessment_id"]:
        policy_rows = await pool.fetch(
            """
            select distinct on (question_number) question_number, strictness_level
            from question_policies
            where assessment_id = $1::uuid
            order by question_number, version desc
            """,
            sub["assessment_id"],
        )
        strict_by_q = {f"Q{r['question_number']}": r["strictness_level"] for r in policy_rows}
    questions = await pool.fetch(
        """
        select question_id, marks_awarded, marks_maximum, source, breakdown,
               approved_by, review_id
        from final_results where submission_id = $1::uuid
        order by question_id
        """,
        uid,
    )
    er_rows = await pool.fetch(
        """
        select question_id, criteria, proposed_marks, breakdown
        from evaluation_results where submission_id = $1::uuid
        order by created_at
        """,
        uid,
    )
    ai_by_qid = {r["question_id"]: r for r in er_rows}
    out_questions: list[dict[str, Any]] = []
    for q in questions:
        ai = ai_by_qid.get(q["question_id"])
        out_questions.append(
            {
                "question_id": q["question_id"],
                "final_marks": float(q["marks_awarded"]),
                "maximum": float(q["marks_maximum"]),
                "source": q["source"],
                "ai_proposed": float(ai["proposed_marks"]) if ai else None,
                "criteria": ai["criteria"] if ai else [],
                "breakdown": q["breakdown"],
                "strictness_level": strict_by_q.get(q["question_id"]),
            }
        )
    return {
        "submission_id": str(sub["id"]),
        "assessment_id": str(sub["assessment_id"]) if sub["assessment_id"] else None,
        "roll_number": sub["roll_number"],
        "status": sub["status"],
        "questions": out_questions,
    }
