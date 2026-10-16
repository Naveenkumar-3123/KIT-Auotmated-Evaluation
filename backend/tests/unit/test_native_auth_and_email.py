"""Unit tests for native PostgreSQL authentication security, mailer, and Qwen3-VL-8B provider."""

import os
from unittest.mock import patch

import pytest

from answer_eval.core.security import (
    create_access_token,
    decode_access_token,
    generate_otp,
    generate_secure_token,
    hash_password,
    verify_password,
)
from answer_eval.inference.factory import create_inference_provider
from answer_eval.models.profiles import ModelProfile, ProviderType
from answer_eval.services.mailer import send_email, send_password_reset_email, send_verification_email


def test_password_hashing():
    raw = "SecurePassword123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_access_token():
    payload = {"sub": "teacher-uuid-123", "email": "prof@college.edu", "role": "teacher"}
    token = create_access_token(payload)
    decoded = decode_access_token(token)
    assert decoded["sub"] == "teacher-uuid-123"
    assert decoded["email"] == "prof@college.edu"
    assert decoded["role"] == "teacher"
    assert "exp" in decoded


def test_otp_generation():
    otp = generate_otp(6)
    assert len(otp) == 6
    assert otp.isdigit()

    token = generate_secure_token()
    assert len(token) > 20


def test_mailer_simulated():
    # Without SMTP credentials configured in test env, mailer logs and returns True (simulated mode) cleanly without throwing
    with patch.dict(os.environ, {"SMTP_USER": "", "SMTP_PASSWORD": ""}):
        result = send_verification_email("teacher@example.com", "654321", "Dr. Rao")
        assert result is True

        result_reset = send_password_reset_email("teacher@example.com", "reset-token-abc")
        assert result_reset is True


def test_gemini_provider_registration():
    profile = ModelProfile(
        model_id="gemini_flash_lite_latest",
        display_name="Google Gemini Flash Lite",
        provider_type=ProviderType.GEMINI,
        context_size=1048576,
    )
    provider = create_inference_provider(profile)
    from answer_eval.inference.gemini_provider import GeminiProvider
    assert isinstance(provider, GeminiProvider)

    caps = provider.get_capabilities()
    assert caps.vision is True
    assert caps.max_context == 1048576
