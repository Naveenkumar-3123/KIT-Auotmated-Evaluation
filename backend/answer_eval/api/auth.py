"""Native JWT verification and backwards-compatible JWKS verifier for API requests.

Identity is ALWAYS derived from a verified token - never from request payloads.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from answer_eval.core.security import JWT_ALGORITHM, JWT_SECRET

logger = logging.getLogger(__name__)

_JWKS_CACHE_TTL_SECONDS = 3600

_ALGORITHMS = {
    "RS256": ["RS256"],
    "RS384": ["RS384"],
    "RS512": ["RS512"],
    "ES256": ["ES256"],
    "HS256": ["HS256"],
}


class AuthError(Exception):
    """Raised when a bearer token cannot be trusted."""


class NativeJWTVerifier:
    def __init__(
        self,
        supabase_url: str = "",
        jwt_secret: str = "",
        *,
        jwks_url: str | None = None,
        jwks_ttl_seconds: int = _JWKS_CACHE_TTL_SECONDS,
        leeway_seconds: int = 30,
    ) -> None:
        self._supabase_url = (supabase_url or "").rstrip("/")
        self._jwt_secret = jwt_secret
        self._jwks_url = (
            jwks_url
            or (f"{self._supabase_url}/auth/v1/.well-known/jwks.json" if self._supabase_url else "")
        )
        self._jwks_ttl = jwks_ttl_seconds
        self._leeway = leeway_seconds
        self._jwks_keys: dict[str, Any] = {}
        self._jwks_fetched_at: float = 0.0

    def verify(self, token: str) -> dict[str, Any]:
        if not token:
            raise AuthError("Token is empty")

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError(f"Malformed token header: {exc}") from exc

        algorithm = header.get("alg", "")
        if algorithm in ("RS256", "RS384", "RS512", "ES256"):
            key = self._asymmetric_key(header.get("kid"))
            claims = self._decode(token, key=key, algorithms=_ALGORITHMS[algorithm], leeway=self._leeway)
        elif algorithm == "HS256":
            if not self._jwt_secret:
                raise AuthError("HS256 token rejected: SUPABASE_JWT_SECRET not configured")
            claims = self._decode(token, key=self._jwt_secret, algorithms=["HS256"], leeway=self._leeway)
        else:
            raise AuthError(f"Unsupported token algorithm '{algorithm}'")

        subject = claims.get("sub")
        if not subject:
            raise AuthError("Token has no 'sub' claim")

        if "user_metadata" not in claims:
            claims["user_metadata"] = {
                "full_name": claims.get("full_name", ""),
                "department_ids": claims.get("department_ids", []),
                "subjects": claims.get("subjects", []),
            }

        return claims

    @staticmethod
    def _decode(token: str, *, key: Any, algorithms: list[str], leeway: int = 0) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                key=key,
                algorithms=algorithms,
                options={"verify_aud": False},
                leeway=leeway,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("Token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError(f"Invalid token: {exc}") from exc

    def _asymmetric_key(self, kid: str | None) -> Any:
        keys = self._get_jwks()
        if not kid:
            if len(keys) == 1:
                return next(iter(keys.values()))
            raise AuthError("Token has no 'kid' header and JWKS contains multiple keys")
        if kid not in keys:
            keys = self._get_jwks(force_refresh=True)
        if kid not in keys:
            raise AuthError(f"Key id '{kid}' not found in JWKS")
        return keys[kid]

    def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not force_refresh
            and self._jwks_keys
            and (now - self._jwks_fetched_at) < self._jwks_ttl
        ):
            return self._jwks_keys

        if not self._jwks_url:
            return self._jwks_keys

        doc = self._fetch_jwks(self._jwks_url)
        parsed: dict[str, Any] = {}
        for entry in doc.get("keys", []):
            kid = entry.get("kid")
            kty = entry.get("kty")
            if not kid:
                continue
            try:
                if kty == "RSA":
                    parsed[kid] = RSAAlgorithm.from_jwk(entry)
                elif kty == "EC":
                    parsed[kid] = ECAlgorithm.from_jwk(entry)
            except Exception as exc:
                logger.warning("Could not parse JWK %s (%s): %s", kid, kty, exc)
        self._jwks_keys = parsed
        self._jwks_fetched_at = now
        return self._jwks_keys

    def _fetch_jwks(self, url: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            raise AuthError(f"Failed to fetch JWKS from {url}: {exc}") from exc


SupabaseJWTVerifier = NativeJWTVerifier
