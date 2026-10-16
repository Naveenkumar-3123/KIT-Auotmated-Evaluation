"""Comprehensive End-to-End Backend Test Suite with Google Gemini API.

Verifies:
1. GeminiProvider direct inference (Text, Vision, Structured Pydantic JSON)
2. Backend API Health (/api/health)
3. Auth Lifecycle (Signup -> Verification -> Login -> Profile fetch)
4. Assessment Lifecycle (Create assessment draft -> Fetch assessment)
5. Answer Key Extraction & Processing (Upload PDF -> Gemini Parse -> Questions & Rubrics)
6. Submission Ingestion & Listing
7. Evaluation & Results Endpoints
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from pydantic import BaseModel, Field

# Ensure standard output can handle UTF-8 safely on Windows console
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

API_BASE = "http://127.0.0.1:8400/api"
SAMPLE_KEY_PDF = ROOT_DIR / "data" / "storage" / "answer-keys" / "0a034c6d-6726-4924-b449-87b62b585ade" / "2b29641e031c-Answer_key.pdf"

class TestReport:
    def __init__(self):
        self.results: list[dict] = []

    def record(self, stage: str, success: bool, details: str, duration_ms: float = 0.0):
        self.results.append({
            "stage": stage,
            "success": success,
            "details": details,
            "duration_ms": duration_ms,
        })
        status_sym = "[PASS]" if success else "[FAIL]"
        print(f"  {status_sym} {stage} ({duration_ms:.1f}ms): {details}")

report = TestReport()


def api_request(method: str, path: str, data: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            return err.code, json.loads(raw)
        except Exception:
            return err.code, {"raw_error": raw}


def multipart_upload(path: str, fields: dict, file_field: str, filename: str, file_bytes: bytes, token: str) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for k, v in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{v}\r\n".encode("utf-8"))

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(b"Content-Type: application/pdf\r\n\r\n")
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            return err.code, json.loads(raw)
        except Exception:
            return err.code, {"raw_error": raw}


async def test_gemini_direct():
    print("\n--- [Step 1] Testing Gemini Provider Direct Inference ---")
    t0 = time.perf_counter()
    from answer_eval.inference.gemini_provider import GeminiProvider
    from answer_eval.inference.types import InferenceRequest, ImageInput

    provider = GeminiProvider()
    healthy = await provider.health_check()
    report.record("Gemini Health Check", healthy, f"Model: {provider.model_name}", (time.perf_counter() - t0) * 1000)

    # Text inference
    t0 = time.perf_counter()
    req = InferenceRequest(request_id=f"test-txt-{uuid.uuid4().hex[:6]}", prompt="State in 5 words why evaluation rubrics matter.")
    resp = await provider.infer(req)
    report.record("Gemini Text Inference", bool(resp.text), f"Response: '{resp.text.strip()}' (Tokens: {resp.usage.total_tokens})", (time.perf_counter() - t0) * 1000)

    # Structured Pydantic schema
    class RubricCriterion(BaseModel):
        code: str = Field(description="Criterion short code e.g. C1")
        description: str = Field(description="What student must state")
        marks: float = Field(description="Points assigned")

    class QuestionSchema(BaseModel):
        question_number: int
        topic: str
        rubric: list[RubricCriterion]

    t0 = time.perf_counter()
    req_struct = InferenceRequest(
        request_id=f"test-struct-{uuid.uuid4().hex[:6]}",
        prompt="Generate a strict grading rubric for Question 1: 'Explain QuickSort time complexity with Best and Worst case'. Total marks: 4.",
    )
    resp_struct = await provider.infer_structured(req_struct, schema=QuestionSchema)
    try:
        parsed = json.loads(resp_struct.text)
        report.record("Gemini Structured JSON", "rubric" in parsed, f"Rubric items: {len(parsed.get('rubric', []))}", (time.perf_counter() - t0) * 1000)
    except Exception as exc:
        report.record("Gemini Structured JSON", False, f"JSON parse error: {exc}", (time.perf_counter() - t0) * 1000)


def test_api_health():
    print("\n--- [Step 2] Testing Backend Health Endpoint ---")
    t0 = time.perf_counter()
    status, body = api_request("GET", "/health")
    ok = status == 200 and body.get("status") == "ok" and body.get("database") is True
    report.record("Backend /api/health", ok, f"Status {status}: {body}", (time.perf_counter() - t0) * 1000)


def test_auth_lifecycle() -> str:
    print("\n--- [Step 3] Testing Teacher Auth Lifecycle ---")
    email = f"gemini_test_{uuid.uuid4().hex[:6]}@evalai.edu"
    password = "SecurePassword123!"
    full_name = "Gemini Evaluation Tester"

    # Signup
    t0 = time.perf_counter()
    status, body = api_request("POST", "/auth/signup", {
        "name": full_name,
        "email": email,
        "password": password,
        "department_ids": ["Computer Science"],
        "subjects": ["Machine Learning"],
    })
    otp = body.get("otp_code")
    report.record("Teacher Signup", status == 201 and bool(otp), f"Email: {email}, OTP: {otp}", (time.perf_counter() - t0) * 1000)

    # Verify Email
    t0 = time.perf_counter()
    status, body = api_request("POST", "/auth/verify-email", {
        "email": email,
        "code": otp or "000000",
    })
    token = body.get("access_token")
    report.record("Email Verification", status == 200 and bool(token), f"Verified. User ID: {body.get('user', {}).get('id')}", (time.perf_counter() - t0) * 1000)

    # Login
    t0 = time.perf_counter()
    status, body = api_request("POST", "/auth/login", {
        "email": email,
        "password": password,
    })
    token = body.get("access_token", token)
    report.record("Teacher Login", status == 200 and bool(token), "JWT token retrieved successfully", (time.perf_counter() - t0) * 1000)

    # Profile Fetch (/auth/me)
    t0 = time.perf_counter()
    status, body = api_request("GET", "/auth/me", token=token)
    profile_data = body.get("profile", {})
    report.record(
        "Fetch Profile (/auth/me)",
        status == 200 and profile_data.get("email") == email,
        f"Teacher Name: {profile_data.get('full_name')}",
        (time.perf_counter() - t0) * 1000
    )

    return token


def test_assessment_flow(token: str) -> str:
    print("\n--- [Step 4] Testing Assessment Creation Flow ---")
    t0 = time.perf_counter()
    status, body = api_request("POST", "/assessments", {
        "title": f"Gemini Test Exam {uuid.uuid4().hex[:4]}",
        "description": "Validation assessment for Gemini multimodal extraction",
    }, token=token)
    assessment_id = body.get("id") or body.get("assessment", {}).get("id")
    report.record("Create Assessment Draft", status in (200, 201) and bool(assessment_id), f"Assessment ID: {assessment_id}", (time.perf_counter() - t0) * 1000)

    # Fetch assessment
    t0 = time.perf_counter()
    status, body = api_request("GET", f"/assessments/{assessment_id}", token=token)
    report.record("Fetch Assessment", status == 200, f"Status: {body.get('status')}", (time.perf_counter() - t0) * 1000)

    # Update assessment details (Save Assessment in UI)
    t0 = time.perf_counter()
    status, body = api_request("PATCH", f"/assessments/{assessment_id}", {
        "title": "CSE 3rd Year · Deep Learning",
        "class_name": "CSE 3rd Year",
        "subject_name": "Deep Learning",
        "pass_percentage": 50.0,
    }, token=token)
    report.record("Save Assessment Details (PATCH /assessments/{id})", status == 200, f"Title: {body.get('assessment', {}).get('title')}", (time.perf_counter() - t0) * 1000)

    return assessment_id


def test_answer_key_flow(token: str, assessment_id: str):
    print("\n--- [Step 5] Testing Answer Key Upload & Gemini Parsing ---")
    if not SAMPLE_KEY_PDF.exists():
        report.record("Answer Key Sample Check", False, f"File not found: {SAMPLE_KEY_PDF}")
        return

    pdf_bytes = SAMPLE_KEY_PDF.read_bytes()
    t0 = time.perf_counter()
    status, body = multipart_upload(
        f"/assessments/{assessment_id}/answer-key",
        fields={},
        file_field="file",
        filename="Sample_Answer_Key.pdf",
        file_bytes=pdf_bytes,
        token=token,
    )
    key_id = body.get("answer_key_id") or body.get("id") or body.get("answer_key", {}).get("id")
    report.record("Upload Answer Key PDF", status in (200, 201, 202) and bool(key_id), f"Key ID: {key_id}, Response status: {status}", (time.perf_counter() - t0) * 1000)

    if not key_id:
        return

    # Poll until parsed (up to 30 seconds)
    print("  ... Polling answer key parse status ...")
    max_polls = 15
    final_payload = None
    for poll in range(max_polls):
        t_poll = time.perf_counter()
        p_status, p_body = api_request("GET", f"/answer-keys/{key_id}", token=token)
        if p_status == 200:
            ak_status = p_body.get("answer_key", {}).get("status")
            questions = p_body.get("questions", [])
            print(f"      [Poll {poll+1}/{max_polls}] status='{ak_status}', questions={len(questions)}")
            if ak_status in ("complete", "parsed", "ready") or len(questions) > 0:
                final_payload = p_body
                report.record("Answer Key Gemini Processing", True, f"Completed in {poll+1} polls! Questions parsed: {len(questions)}", (time.perf_counter() - t0) * 1000)
                break
            if ak_status == "failed":
                err = p_body.get("answer_key", {}).get("parse_error", "Unknown error")
                report.record("Answer Key Gemini Processing", False, f"Parsing failed: {err}", (time.perf_counter() - t0) * 1000)
                break
        time.sleep(2)

    if final_payload:
        questions = final_payload.get("questions", [])
        if questions:
            q1 = questions[0]
            concepts = q1.get("concepts", [])
            diagrams = q1.get("diagrams", [])
            print(f"      Q{q1.get('question_number')}: '{q1.get('question_text', '')[:60]}...'")
            print(f"      Max Marks: {q1.get('maximum_marks')}, Concepts: {len(concepts)}, Diagrams: {len(diagrams)}")
            report.record("Answer Key Structure Verification", len(questions) > 0, f"Q1 has {len(concepts)} concepts & {len(diagrams)} diagrams")


def test_submissions_flow(token: str, assessment_id: str):
    print("\n--- [Step 6] Testing Student Submission Ingestion ---")
    student_pdf_bytes = (
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources <<>> /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 50 >>\nstream\nStudent Roll: 24CSE999 Answer Sheet Sample Page 1\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n0000000217 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n300\n%%EOF"
    )
    t0 = time.perf_counter()
    status, body = multipart_upload(
        f"/assessments/{assessment_id}/student-zip",
        fields={},
        file_field="file",
        filename="24CSE999.pdf",
        file_bytes=student_pdf_bytes,
        token=token,
    )
    valid_count = body.get("valid", 0) if isinstance(body, dict) else 0
    students = body.get("students", []) if isinstance(body, dict) else []
    sub_id = students[0].get("submission_id") if students else None
    report.record("Student PDF Ingestion", status == 200 and valid_count > 0, f"Valid: {valid_count}, Submission ID: {sub_id}", (time.perf_counter() - t0) * 1000)

    # Fetch submissions list
    t0 = time.perf_counter()
    status, body = api_request("GET", f"/assessments/{assessment_id}/students", token=token)
    subs = body if isinstance(body, list) else body.get("students", [])
    count = len(subs) if isinstance(subs, list) else 0
    report.record("List Students/Submissions", status == 200 and count > 0, f"Submissions count: {count}", (time.perf_counter() - t0) * 1000)


def test_results_and_analytics(token: str, assessment_id: str):
    print("\n--- [Step 7] Testing Results & Analytics Endpoints ---")
    t0 = time.perf_counter()
    status, body = api_request("GET", f"/assessments/{assessment_id}/results", token=token)
    report.record("Assessment Results Endpoint", status == 200, f"Status: {status}", (time.perf_counter() - t0) * 1000)


async def main():
    print("=================================================================")
    print("       EvalAI Backend Verification with Google Gemini API        ")
    print("=================================================================")
    
    # 1. Gemini Direct
    await test_gemini_direct()

    # 2. Health
    test_api_health()

    # 3. Auth
    token = test_auth_lifecycle()

    # 4. Assessment
    assessment_id = test_assessment_flow(token)

    # 5. Answer Key
    test_answer_key_flow(token, assessment_id)

    # 6. Submissions
    test_submissions_flow(token, assessment_id)

    # 7. Results
    test_results_and_analytics(token, assessment_id)

    print("\n=================================================================")
    print("                      Test Suite Summary                         ")
    print("=================================================================")
    passed = sum(1 for r in report.results if r["success"])
    total = len(report.results)
    print(f"Passed: {passed}/{total} stages ({passed/total*100:.1f}%)")
    for r in report.results:
        mark = "[PASS]" if r["success"] else "[FAIL]"
        print(f"  {mark} {r['stage']}: {r['details']}")
    print("=================================================================")


if __name__ == "__main__":
    asyncio.run(main())
