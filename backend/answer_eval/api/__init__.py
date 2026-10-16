"""EvalAI HTTP API package (FastAPI).

The API is the control plane described in docs/architecture: it validates
Supabase JWTs, persists durable state in Supabase Postgres and coordinates the
perception/grading pipeline plus the distributed evaluation workers.
"""
