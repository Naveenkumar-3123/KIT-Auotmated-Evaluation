"""Real analytics from finalized results (Milestone 18, specs #75-#79)."""

from __future__ import annotations

import statistics
from typing import Any

import asyncpg


def _pct(value: float, maximum: float) -> float | None:
    return round(value / maximum * 100.0, 2) if maximum > 0 else None


async def _completed_criteria_rows(pool: asyncpg.Pool, assessment_id: str):
    return await pool.fetch(
        """
        select er.criteria from evaluation_results er
        join submissions s on s.id = er.submission_id
        where er.assessment_id = $1::uuid and s.status = 'completed'
        """,
        __import__("uuid").UUID(assessment_id),
    )


async def class_analytics(pool: asyncpg.Pool, assessment_id: str) -> dict[str, Any]:
    uid = __import__("uuid").UUID(assessment_id)
    meta = await pool.fetchrow(
        "select title, total_marks, pass_percentage, status from assessments where id = $1::uuid",
        uid,
    )
    if meta is None:
        return {}
    maximum = float(meta["total_marks"] or 0)
    if maximum <= 0:
        fallback = await pool.fetchval(
            "select max(marks_maximum) from final_results where assessment_id = $1::uuid", uid
        )
        maximum = float(fallback or 0)
    pass_mark = float(meta["pass_percentage"] or 0)
    counts = await pool.fetchrow(
        """select count(*)::int as total,
                  count(*) filter (where status = 'completed')::int as completed,
                  count(*) filter (where status = 'waiting_for_review')::int as waiting
           from submissions where assessment_id = $1::uuid""",
        uid,
    )
    totals_rows = await pool.fetch(
        """select f.submission_id, sum(f.marks_awarded) as total
           from final_results f join submissions s on s.id = f.submission_id
           where f.assessment_id = $1::uuid and s.status = 'completed'
           group by f.submission_id""",
        uid,
    )
    totals = [round(float(r["total"]), 2) for r in totals_rows]
    percentages = [_pct(t, maximum) or 0.0 for t in totals]
    passed_count = sum(1 for p in percentages if p >= pass_mark)

    per_question = await pool.fetch(
        """select f.question_id, avg(f.marks_awarded)::numeric as avg_awarded,
                  max(f.marks_maximum) as max_marks,
                  sum(f.marks_maximum - f.marks_awarded) as lost,
                  count(*)::int as graded
           from final_results f join submissions s on s.id = f.submission_id
           where f.assessment_id = $1::uuid and s.status = 'completed'
           group by f.question_id order by f.question_id""",
        uid,
    )
    questions = []
    for q in per_question:
        qmax = float(q["max_marks"] or 0)
        avg = round(float(q["avg_awarded"]), 2)
        attainment = _pct(avg, qmax) or 0.0
        questions.append(
            {
                "question_id": q["question_id"],
                "average_awarded": avg,
                "maximum": qmax,
                "attainment_pct": attainment,
                "difficulty": ("easy" if attainment >= 75 else "moderate" if attainment >= 50 else "hard"),
                "failure_rate": round(1.0 - attainment / 100.0, 4) if qmax > 0 else 0.0,
                "avg_marks_lost": round(float(q["lost"] or 0) / int(q["graded"] or 1), 2),
            }
        )

    crit_acc: dict[str, dict[str, float]] = {}
    for row in await _completed_criteria_rows(pool, assessment_id):
        for c in row["criteria"] or []:
            cid = str(c.get("criterion_id") or "?")
            bucket = crit_acc.setdefault(cid, {"sum": 0.0, "max": 0.0, "n": 0.0})
            mx = float(c.get("maximum_marks") or 0)
            bucket["sum"] += min(float(c.get("proposed_marks") or 0), mx)
            bucket["max"] += mx
            bucket["n"] += 1
    concepts = []
    for cid, b in sorted(crit_acc.items()):
        att = round(b["sum"] / b["max"] * 100.0, 2) if b["max"] > 0 else 0.0
        concepts.append({"criterion_id": cid, "attainment_pct": att, "samples": int(b["n"]),
                         "difficulty": ("easy" if att >= 75 else "moderate" if att >= 50 else "hard")})
    concepts.sort(key=lambda c: c["attainment_pct"])

    review_freq = await pool.fetchval(
        "select count(*)::int from teacher_reviews where assessment_id = $1::uuid", uid
    )
    distribution = {
        "0-25": sum(1 for p in percentages if p <= 25),
        "26-50": sum(1 for p in percentages if 25 < p <= 50),
        "51-75": sum(1 for p in percentages if 50 < p <= 75),
        "76-100": sum(1 for p in percentages if p > 75),
    }
    total_students = int(counts["total"])
    completed_n = len(totals)
    return {
        "assessment_id": assessment_id,
        "title": meta["title"],
        "status": meta["status"],
        "total_marks": maximum,
        "pass_percentage": pass_mark,
        "students": {"total": total_students, "completed": int(counts["completed"]),
                     "waiting_for_review": int(counts["waiting"])},
        "based_on_completed": completed_n,
        "partial_note": (f"Analytics based on {completed_n} of {total_students} completed submissions."
                          if completed_n < total_students else None),
        "class_average": round(statistics.fmean(totals), 2) if totals else None,
        "class_average_pct": round(statistics.fmean(percentages), 2) if percentages else None,
        "median_pct": round(statistics.median(percentages), 2) if percentages else None,
        "highest": round(max(totals), 2) if totals else None,
        "lowest": round(min(totals), 2) if totals else None,
        "pass_count": passed_count,
        "fail_count": completed_n - passed_count,
        "pass_percentage_actual": round(passed_count / completed_n * 100.0, 2) if completed_n else None,
        "score_distribution": distribution,
        "per_question": questions,
        "concept_difficulty": concepts[:20],
        "teacher_review_frequency": int(review_freq or 0),
    }


async def student_analytics(pool: asyncpg.Pool, submission_id: str) -> dict[str, Any]:
    uid = __import__("uuid").UUID(submission_id)
    sub = await pool.fetchrow(
        "select id, roll_number, status, assessment_id from submissions where id = $1::uuid", uid
    )
    if sub is None:
        return {}
    aid = sub["assessment_id"]
    rows = await pool.fetch(
        """select question_id, marks_awarded, marks_maximum, source from final_results
           where submission_id = $1::uuid order by question_id""",
        uid,
    )
    total = round(sum(float(r["marks_awarded"]) for r in rows), 2)
    maximum = round(sum(float(r["marks_maximum"]) for r in rows), 2)
    meta = await pool.fetchrow(
        "select total_marks, pass_percentage from assessments where id = $1::uuid", aid
    )
    overall_max = float(meta["total_marks"] or 0) if meta else 0.0
    if overall_max <= 0:
        overall_max = maximum  # sum of this student's graded question maxima
    pass_mark = float(meta["pass_percentage"] or 0) if meta else 0.0
    overall_pct = _pct(total, overall_max)

    rank = None
    if sub["status"] == "completed":
        higher = await pool.fetchval(
            """select count(distinct f.submission_id)::int
               from final_results f join submissions s on s.id = f.submission_id
               where f.assessment_id = $1::uuid and s.id <> $2::uuid and s.status = 'completed'
               group by f.submission_id
               having sum(f.marks_awarded) > $3::numeric""",
            aid, uid, total,
        )
        peer_count = await pool.fetchval(
            """select count(distinct f.submission_id)::int
               from final_results f join submissions s on s.id = f.submission_id
               where f.assessment_id = $1::uuid and s.id <> $2::uuid and s.status = 'completed'""",
            aid, uid,
        )
        rank = (higher or 0) + 1
        _ = peer_count

    strengths: list[dict[str, Any]] = []
    weaknesses: list[dict[str, Any]] = []
    missing_concepts: list[str] = []
    math_steps: list[dict[str, Any]] = []
    for row in await pool.fetch(
        "select criteria from evaluation_results where submission_id = $1::uuid", uid
    ):
        for c in row["criteria"] or []:
            cid = str(c.get("criterion_id") or "?")
            mx = float(c.get("maximum_marks") or 0)
            got = float(c.get("proposed_marks") or 0)
            att = _pct(got, mx) or 0.0
            entry = {"criterion_id": cid, "description": str(c.get("criterion") or ""),
                     "awarded": got, "maximum": mx, "attainment_pct": att}
            if str(c.get("status")) == "unsupported":
                missing_concepts.append(entry)
            elif att >= 75:
                strengths.append(entry)
            elif att <= 40:
                weaknesses.append(entry)
            if cid.startswith("M"):
                math_steps.append({**entry, "detail": str(c.get("reason") or "")})

    pending_review = await pool.fetchval(
        """select count(*)::int from teacher_reviews
           where submission_id = $1::uuid and status = 'pending'""", uid,
    )
    return {
        "assessment_id": str(aid),
        "submission_id": str(sub["id"]), "roll_number": sub["roll_number"],
        "status": sub["status"], "total": total, "maximum": maximum,
        "overall_max": overall_max, "percentage": overall_pct,
        "passed": (overall_pct >= pass_mark) if overall_pct is not None else None,
        "rank": rank,
        "questions": [{"question_id": r["question_id"], "awarded": float(r["marks_awarded"]),
                       "maximum": float(r["marks_maximum"]), "source": r["source"]} for r in rows],
        "strengths": strengths[:15], "weaknesses": weaknesses[:15],
        "missing_concepts": missing_concepts[:15],
        "needs_review": ["pending teacher reviews open"] if pending_review else [],
        "math_steps": math_steps[:20],
    }

