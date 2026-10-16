"""Unit tests for SupabaseJWTVerifier (HS256 + RS256/JWKS)."""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from answer_eval.api.auth import AuthError, SupabaseJWTVerifier

SECRET = "test-jwt-secret-signing-key"


def _hs_token(claims: dict[str, Any], secret: str = SECRET) -> str:
    return pyjwt.encode(claims, secret, algorithm="HS256")


class StaticJWKSVerifier(SupabaseJWTVerifier):
    """RS256 verifier with an in-memory JWKS (no network)."""

    def __init__(self, jwks: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._static_jwks = jwks

    def _fetch_jwks(self, url: str) -> dict[str, Any]:  # noqa: ARG002
        return self._static_jwks


def test_hs256_valid_token_yields_claims() -> None:
    verifier = SupabaseJWTVerifier(supabase_url="", jwt_secret=SECRET)
    token = _hs_token({"sub": "user-1", "email": "t@example.com", "exp": int(time.time()) + 300})
    claims = verifier.verify(token)
    assert claims["sub"] == "user-1"
    assert claims["email"] == "t@example.com"


def test_hs256_wrong_secret_rejected() -> None:
    verifier = SupabaseJWTVerifier(jwt_secret="another-secret")
    token = _hs_token({"sub": "user-1", "exp": int(time.time()) + 300})
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_expired_token_rejected() -> None:
    verifier = SupabaseJWTVerifier(jwt_secret=SECRET, leeway_seconds=0)
    token = _hs_token({"sub": "user-1", "exp": int(time.time()) - 10})
    with pytest.raises(AuthError, match="expired"):
        verifier.verify(token)


def test_default_leeway_tolerates_minor_clock_skew_but_not_old_expiry() -> None:
    verifier = SupabaseJWTVerifier(jwt_secret=SECRET)
    recent = _hs_token({"sub": "user-1", "exp": int(time.time()) - 5})
    assert verifier.verify(recent)["sub"] == "user-1"  # inside 30s leeway
    stale = _hs_token({"sub": "user-1", "exp": int(time.time()) - 120})
    with pytest.raises(AuthError, match="expired"):
        verifier.verify(stale)


def test_future_iat_within_leeway_accepted() -> None:
    verifier = SupabaseJWTVerifier(jwt_secret=SECRET, leeway_seconds=30)
    token = _hs_token({"sub": "user-1", "iat": int(time.time()) + 10, "nbf": int(time.time()) + 10, "exp": int(time.time()) + 300})
    claims = verifier.verify(token)
    assert claims["sub"] == "user-1"


def test_missing_secret_rejects_hs256() -> None:
    verifier = SupabaseJWTVerifier()
    token = _hs_token({"sub": "user-1"})
    with pytest.raises(AuthError, match="SUPABASE_JWT_SECRET"):
        verifier.verify(token)


def test_garbage_token_rejected() -> None:
    verifier = SupabaseJWTVerifier(jwt_secret=SECRET)
    with pytest.raises(AuthError):
        verifier.verify("not-a-token")


def test_rs256_via_jwks() -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    jwk_json: dict[str, Any] = pyjwt.algorithms.RSAAlgorithm.to_jwk(
        key.public_key(), as_dict=True
    )  # type: ignore[assignment]
    jwk_json["kid"] = "test-kid"
    jwk_json["alg"] = "RS256"
    verifier = StaticJWKSVerifier(
        {"keys": [jwk_json]},
        supabase_url="https://project.supabase.co",
        jwt_secret="",
    )
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = pyjwt.encode({"sub": "rs-user"}, private_pem, algorithm="RS256", headers={"kid": "test-kid"})
    claims = verifier.verify(token)
    assert claims["sub"] == "rs-user"


def test_rs256_unknown_kid_rejected() -> None:
    verifier = StaticJWKSVerifier({"keys": []}, supabase_url="https://project.supabase.co")
    header = pyjwt.get_unverified_header(_hs_token({"sub": "x"}))
    assert header["alg"] == "HS256"  # sanity: helper produces HS256
    with pytest.raises(AuthError, match="JWKS"):
        verifier._asymmetric_key("missing-kid")


def test_es256_jwk_supported() -> None:
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    jwk_doc: dict[str, Any] = pyjwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)  # type: ignore[assignment]
    jwk_doc["kid"] = "ec-kid"
    verifier = StaticJWKSVerifier({"keys": [jwk_doc]}, supabase_url="https://p.supabase.co")
    assert "ec-kid" in verifier._get_jwks()


def test_jwks_url_override_wins_over_project_url() -> None:
    fetched: dict[str, str] = {}

    class RecordingVerifier(SupabaseJWTVerifier):
        def _fetch_jwks(self, url: str) -> dict[str, Any]:
            fetched["url"] = url
            return {"keys": []}

    verifier = RecordingVerifier(
        supabase_url="https://project.supabase.co",
        jwks_url="https://custom.example/jwks.json",
    )
    verifier._get_jwks()
    assert fetched["url"] == "https://custom.example/jwks.json"
