"""Optional FastAPI surface (Module 18): submit / status / result / review.

The service functions in jobs.service are the real contract; this thin HTTP
layer exists so a frontend can poll progress. Run with:
    uvicorn answer_eval.jobs.api:create_app --factory
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from answer_eval.jobs.queue import create_queue
from answer_eval.jobs.service import EvaluationJobService
from answer_eval.jobs.store import SQLiteJobStore


class SubmitRequest(BaseModel):
    submission_id: str = Field(description="Unique submission id (idempotency key)")
    pdf_path: str = Field(description="Server-side path to the uploaded PDF")
    rubrics: dict[str, Any] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    decisions: dict[str, Any] = Field(
        description='{"Q4": {"approved": true, "final_marks": 8.5, "reviewer_notes": "..."}}'
    )


def create_app(store=None) -> FastAPI:
    app = FastAPI(title="Answer Paper Evaluation — Jobs API", version="0.1.0")
    job_service = EvaluationJobService(store or SQLiteJobStore(), create_queue())

    @app.post("/submissions", status_code=202)
    def submit_submission(body: SubmitRequest) -> dict:
        job, created = job_service.submit(body.submission_id, body.pdf_path, body.rubrics)
        return {
            "submission_id": job.submission_id,
            "job_id": job.job_id,
            "status": "queued" if created else job.status.value,
            "duplicate": not created,
        }

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        status = job_service.status(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'")
        return status

    @app.get("/submissions/{submission_id}/result")
    def get_result(submission_id: str) -> dict:
        result = job_service.result(submission_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No result yet for '{submission_id}'")
        return {"submission_id": submission_id, **result}

    @app.post("/jobs/{job_id}/review")
    def resume_after_review(job_id: str, body: ReviewRequest) -> dict:
        try:
            job = job_service.resume_after_review(job_id, body.decisions)
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return {"job_id": job.job_id, "status": job.status.value if hasattr(job.status, "value") else str(job.status)}

    return app
