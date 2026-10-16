"""Cross-cutting API middleware: request IDs + access logging, and a
consistent JSON error envelope so the frontend can handle failures uniformly.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger("evalai.api")

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id and logs method/path/status/duration."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - logged by handler; re-raised for server
            logger.exception(
                "request failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000.0
        response.headers[_REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces essential HTTP security headers across all API responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
        return response


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter for sensitive authentication endpoints to protect against brute-force attacks."""

    def __init__(self, app: FastAPI, *, window_seconds: int = 60):
        super().__init__(app)
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}
        self._sensitive_paths = {
            "/api/auth/login": 12,
            "/api/auth/signup": 8,
            "/api/auth/verify-email": 15,
            "/api/auth/resend-code": 5,
            "/api/auth/forgot-password": 5,
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path.rstrip("/")
        if path in self._sensitive_paths:
            max_allowed = self._sensitive_paths[path]
            client_ip = request.client.host if request.client else "127.0.0.1"
            key = f"{client_ip}:{path}"
            now = time.time()
            cutoff = now - self._window

            history = self._requests.get(key, [])
            history = [t for t in history if t > cutoff]
            if len(history) >= max_allowed:
                retry_after = int(self._window - (now - history[0])) if history else self._window
                return JSONResponse(
                    status_code=429,
                    content=_error_payload(
                        request,
                        "rate_limited",
                        f"Too many requests. Please wait {max(1, retry_after)} seconds before trying again.",
                    ),
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            history.append(now)
            self._requests[key] = history

        return await call_next(request)


def _error_payload(request: Request, code: str, message: str) -> dict:
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, f"http_{exc.status_code}", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = f"Invalid request: {location} {first.get('msg', 'validation error')}".strip()
        return JSONResponse(status_code=422, content=_error_payload(request, "validation_error", message))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=_error_payload(request, "internal_error", "Internal server error"))
