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
            select question_number, strictness_level, version
            from question_policies
            where assessment_id = $1::uuid
            order by question_number, version desc
            """,
            sub["assessment_id"],
        )
        for r in policy_rows:
            k = f"Q{r['question_number']}"
            if k not in strict_by_q:
                strict_by_q[k] = r["strictness_level"]
    questions = await pool.fetch(
        """
        select question_id, marks_awarded, marks_maximum, source, breakdown,
               approved_by, review_id
        from final_results where submission_id = $1::uuid
        order by question_id
        """,
        uid,
    )
    er_rows: list[Any] = []
    try:
        er_rows = await pool.fetch(
            """
            select question_id, marks_awarded as proposed_marks, marks_maximum, raw_evaluation_json
            from evaluation_results where submission_id = $1::uuid
            order by created_at
            """,
            uid,
        )
    except Exception:
        er_rows = []

    ai_by_qid = {r["question_id"]: r for r in er_rows}
    out_questions: list[dict[str, Any]] = []
    if questions:
        for q in questions:
            ai = ai_by_qid.get(q["question_id"])
            crit = []
            if ai and ai.get("raw_evaluation_json"):
                try:
                    import json as _j
                    crit = _j.loads(ai["raw_evaluation_json"]).get("criteria", [])
                except Exception:
                    pass
            out_questions.append(
                {
                    "question_id": q["question_id"],
                    "final_marks": float(q["marks_awarded"]),
                    "maximum": float(q["marks_maximum"]),
                    "source": q["source"],
                    "ai_proposed": float(ai["proposed_marks"]) if ai and ai["proposed_marks"] is not None else None,
                    "criteria": crit,
                    "breakdown": q["breakdown"],
                    "strictness_level": strict_by_q.get(q["question_id"]),
                }
            )
    elif er_rows:
        for er in er_rows:
            qid = er["question_id"]
            marks_val = float(er["proposed_marks"]) if er["proposed_marks"] is not None else 0.0
            max_val = float(er["marks_maximum"]) if er["marks_maximum"] is not None else 0.0
            crit = []
            bd = {}
            if er.get("raw_evaluation_json"):
                try:
                    import json as _j
                    parsed = _j.loads(er["raw_evaluation_json"])
                    crit = parsed.get("criteria", [])
                    bd = parsed.get("breakdown", {})
                except Exception:
                    pass
            out_questions.append(
                {
                    "question_id": qid,
                    "final_marks": marks_val,
                    "maximum": max_val,
                    "source": "ai_proposed",
                    "ai_proposed": marks_val,
                    "criteria": crit,
                    "breakdown": bd,
                    "strictness_level": strict_by_q.get(qid),
                }
            )
    else:
        # Fall back to durable job record payload
        job_row = await pool.fetchrow(
            """
            select payload from job_records
            where submission_id = $1
            order by created_at desc limit 1
            """,
            submission_id,
        )
        if not job_row:
            try:
                import sqlite3 as _sqlite3, os as _os
                if _os.path.exists("data/jobs.db"):
                    _conn = _sqlite3.connect("data/jobs.db")
                    _r = _conn.execute("SELECT payload FROM jobs WHERE submission_id = ? ORDER BY created_at DESC LIMIT 1", (submission_id,)).fetchone()
                    _conn.close()
                    if _r and _r[0]:
                        job_row = {"payload": _r[0]}
            except Exception:
                pass
        if job_row and job_row["payload"]:
            import json as _json
            jp = job_row["payload"]
            if isinstance(jp, str):
                jp = _json.loads(jp)
            summary = jp.get("result_summary") or {}
            q_map = summary.get("questions") or {}
            if not q_map:
                rr = jp.get("review_request") or {}
                q_map = rr.get("awaiting_review") or {}
            if not q_map:
                q_map = jp.get("rubrics") or {}

            for qid, qdata in q_map.items():
                if not isinstance(qdata, dict):
                    continue
                marks = qdata.get("final_marks") if qdata.get("final_marks") is not None else qdata.get("proposed_marks")
                max_m = qdata.get("maximum_marks")
                crit_list = qdata.get("criteria") or []
                bd_dict = {"feedback": qdata.get("feedback"), "reasons": qdata.get("reasons")}
                out_questions.append(
                    {
                        "question_id": str(qid),
                        "final_marks": float(marks) if marks is not None else 0.0,
                        "maximum": float(max_m) if max_m is not None else 0.0,
                        "source": "review" if sub["status"] == "waiting_for_review" else "pending",
                        "ai_proposed": float(marks) if marks is not None else None,
                        "criteria": crit_list,
                        "breakdown": bd_dict,
                        "strictness_level": strict_by_q.get(str(qid)),
                    }
                )

    return {
        "submission_id": str(sub["id"]),
        "assessment_id": str(sub["assessment_id"]) if sub["assessment_id"] else None,
        "roll_number": sub["roll_number"],
        "status": sub["status"],
        "questions": out_questions,
    }
