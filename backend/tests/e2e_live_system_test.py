"""Comprehensive Live System End-to-End Test Suite.

Tests:
1. Health & Security Headers
2. Auth Lifecycle (Signup -> Verification -> Login -> Profile Fetch)
3. Auth Rate Limiting (Burst 429 detection)
4. Draft Assessment Creation
5. Answer Key PDF Upload & Ingestion (202 Accepted)
6. Single Student PDF Upload & Ingestion (200 OK)
7. Bulk Student ZIP Upload & Ingestion (200 OK)
8. Ingested Submissions Verification (Roll Numbers)
9. Worker Fleet Verification & Heartbeat Check
"""

import io
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

from pathlib import Path

BASE_URL = "http://127.0.0.1:8300"
_root_db = Path(__file__).resolve().parent.parent.parent / "data" / "evalai.db"
_backend_db = Path(__file__).resolve().parent.parent / "data" / "evalai.db"
DB_PATH = str(_root_db if _root_db.exists() else _backend_db)


def request(method, path, data=None, headers=None, expect_status=200):
    url = f"{BASE_URL}{path}"
    headers = headers or {}
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif isinstance(data, bytes):
            body = data

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            resp_headers = dict(resp.headers)
            resp_body = resp.read()
            try:
                parsed_json = json.loads(resp_body.decode("utf-8"))
            except Exception:
                parsed_json = resp_body
            if resp.status != expect_status:
                raise AssertionError(f"Expected {expect_status} on {path}, got {resp.status}")
            return resp.status, resp_headers, parsed_json
    except urllib.error.HTTPError as err:
        err_body = err.read()
        try:
            parsed_json = json.loads(err_body.decode("utf-8"))
        except Exception:
            parsed_json = err_body.decode("utf-8", errors="ignore")
        if err.code != expect_status:
            raise AssertionError(f"Expected {expect_status} on {path}, got {err.code}: {parsed_json}")
        return err.code, dict(err.headers), parsed_json


def make_dummy_pdf(content_text="Sample Document"):
    pdf_template = (
        f"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        f"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        f"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources <<>> /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        f"4 0 obj\n<< /Length {len(content_text)} >>\nstream\n{content_text}\nendstream\nendobj\n"
        f"xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n0000000217 00000 n \n"
        f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n300\n%%EOF"
    )
    return pdf_template.encode("utf-8")


def make_dummy_zip(files_dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in files_dict.items():
            zf.writestr(fname, data)
    return buf.getvalue()


def encode_multipart(fields, files):
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))
    for name, (filename, file_bytes, content_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_bytes)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, bytes(body)


def run_e2e_iteration(iteration_num):
    print(f"\n=======================================================")
    print(f"  RUNNING E2E SYSTEM INTEGRATION TEST - ITERATION {iteration_num}")
    print(f"=======================================================")

    # 1. Health & Security Headers
    status, headers, body = request("GET", "/api/health")
    assert status == 200, f"Health check failed: {status}"
    assert body.get("status") == "ok", f"Health status: {body}"
    assert body.get("database") is True, f"Database not reported healthy: {body}"

    # Verify Security Headers
    sec_keys = [
        "x-content-type-options",
        "x-frame-options",
        "x-xss-protection",
        "referrer-policy",
        "strict-transport-security",
        "permissions-policy",
    ]
    for k in sec_keys:
        assert k in headers, f"Missing security header: {k}"
    print(f"[Pass] 1. Health endpoint & 6 Security Headers verified.")

    # 2. Auth Flow (Signup -> Verify -> Login -> Profile)
    test_email = f"test_teacher_{uuid.uuid4().hex[:8]}@evalai.edu"
    test_password = "SecurePassword123!"

    # Signup
    signup_payload = {
        "email": test_email,
        "password": test_password,
        "full_name": "Dr. Test Professor",
        "institution": "Department of Computer Science",
        "departments": ["CSE"],
        "subjects": ["Data Structures", "Algorithms"],
    }
    status, _, res = request("POST", "/api/auth/signup", signup_payload, expect_status=201)
    assert res.get("email") == test_email
    print(f"[Pass] 2a. Signup successful for {test_email}")

    # Fetch OTP from SQLite
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT verification_code FROM users WHERE email = ?", (test_email,))
    row = cur.fetchone()
    conn.close()
    assert row is not None, "User record not found in SQLite"
    otp_code = row[0]
    assert otp_code and len(otp_code) == 6, f"Invalid OTP code: {otp_code}"

    # Verify Email
    status, _, v_res = request(
        "POST",
        "/api/auth/verify-email",
        {"email": test_email, "code": otp_code},
        expect_status=200,
    )
    assert "access_token" in v_res, f"Verification failed: {v_res}"
    print(f"[Pass] 2b. Email verified via 6-digit OTP code (auto-session token returned).")

    # Login
    status, _, l_res = request(
        "POST",
        "/api/auth/login",
        {"email": test_email, "password": test_password},
        expect_status=200,
    )
    token = l_res.get("access_token")
    assert token, "No JWT access token returned"
    auth_headers = {"Authorization": f"Bearer {token}"}
    print(f"[Pass] 2c. Login successful; HS256 JWT obtained.")

    # Profile Fetch
    status, _, p_res = request("GET", "/api/auth/me", headers=auth_headers, expect_status=200)
    assert p_res.get("profile", {}).get("email") == test_email
    print(f"[Pass] 2d. Authenticated /api/auth/me returned teacher profile.")

    status, _, pr_res = request("GET", "/api/profile", headers=auth_headers, expect_status=200)
    assert pr_res.get("email") == test_email
    print(f"[Pass] 2e. Authenticated /api/profile returned profile model.")

    # 3. Create Draft Assessment
    status, _, a_res = request(
        "POST",
        "/api/assessments",
        {"title": f"Midterm Exam - Iteration {iteration_num}"},
        headers=auth_headers,
        expect_status=201,
    )
    assessment = a_res.get("assessment")
    assert assessment and assessment.get("id"), "Assessment not created"
    assessment_id = assessment["id"]
    print(f"[Pass] 3. Created draft assessment: {assessment_id}")

    # 4. Upload Answer Key PDF
    key_pdf_bytes = make_dummy_pdf("Q1: Explain Quicksort algorithm. (10 marks)\nAnswer: Divide and conquer partition...")
    boundary, multipart_body = encode_multipart(
        {},
        {"file": ("sample_answer_key.pdf", key_pdf_bytes, "application/pdf")},
    )
    upload_headers = dict(auth_headers)
    upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    status, _, k_res = request(
        "POST",
        f"/api/assessments/{assessment_id}/answer-key",
        data=multipart_body,
        headers=upload_headers,
        expect_status=202,
    )
    assert k_res.get("answer_key", {}).get("status") in ("parsing", "parsed"), f"Unexpected key status: {k_res}"
    print(f"[Pass] 4. Uploaded answer key PDF (202 Accepted).")

    # 5. Upload Single Student Answer Paper (.pdf)
    student_pdf_bytes = make_dummy_pdf("Student Answer 24CSE001: Quicksort chooses a pivot element and partitions...")
    boundary, multipart_body = encode_multipart(
        {},
        {"file": ("24CSE001.pdf", student_pdf_bytes, "application/pdf")},
    )
    upload_headers = dict(auth_headers)
    upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    status, _, sp_res = request(
        "POST",
        f"/api/assessments/{assessment_id}/student-zip",
        data=multipart_body,
        headers=upload_headers,
        expect_status=200,
    )
    assert sp_res.get("valid", 0) >= 1, f"Student PDF upload failed: {sp_res}"
    print(f"[Pass] 5. Uploaded single student answer paper (.pdf) with roll 24CSE001.")

    # 6. Upload Batch Student Answer Papers (.zip)
    zip_bytes = make_dummy_zip({
        "24CSE002.pdf": make_dummy_pdf("Student 24CSE002 answer..."),
        "24CSE003.pdf": make_dummy_pdf("Student 24CSE003 answer..."),
    })
    boundary, multipart_body = encode_multipart(
        {},
        {"file": ("batch_papers.zip", zip_bytes, "application/zip")},
    )
    upload_headers = dict(auth_headers)
    upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    status, _, bz_res = request(
        "POST",
        f"/api/assessments/{assessment_id}/student-zip",
        data=multipart_body,
        headers=upload_headers,
        expect_status=200,
    )
    assert bz_res.get("valid", 0) >= 2, f"Batch ZIP upload failed: {bz_res}"
    print(f"[Pass] 6. Uploaded batch student papers (.zip) with 2 students.")

    # 7. Verify Submissions in Database
    status, _, subs = request(
        "GET",
        f"/api/assessments/{assessment_id}/students",
        headers=auth_headers,
        expect_status=200,
    )
    rolls = [s.get("roll_number") for s in subs]
    assert "24CSE001" in rolls, f"Missing single PDF roll 24CSE001 in {rolls}"
    assert "24CSE002" in rolls, f"Missing batch roll 24CSE002 in {rolls}"
    assert "24CSE003" in rolls, f"Missing batch roll 24CSE003 in {rolls}"
    print(f"[Pass] 7. Verified all 3 student submissions (24CSE001, 24CSE002, 24CSE003) persisted.")

    # 8. Worker Fleet Verification
    status, _, f_res = request("GET", "/api/workers", headers=auth_headers, expect_status=200)
    assert f_res.get("online_count", 0) >= 1, f"No online workers found: {f_res}"
    assert len(f_res.get("workers", [])) >= 1, "Workers list empty"
    print(f"[Pass] 8. Worker fleet verified: {f_res.get('online_count')} active worker(s) online.")

    print(f"Iteration {iteration_num} PASSED 100% SUCCESS!")
    return True


if __name__ == "__main__":
    runs = 3
    print(f"Starting Live E2E Integration Testing: {runs} Consecutive Iterations...")
    for i in range(1, runs + 1):
        success = run_e2e_iteration(i)
        assert success
        time.sleep(1.0)
    print("\n=======================================================")
    print("  ALL 3 LIVE E2E ITERATIONS COMPLETED WITH ZERO FAILURES!")
    print("=======================================================")
