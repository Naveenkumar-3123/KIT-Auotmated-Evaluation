"""Auth-related backend endpoints for native PostgreSQL authentication and automated email verification.

Fully replaces Supabase Auth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status

from answer_eval.api.deps import CurrentTeacher, require_database
from answer_eval.api.models import (
    ForgotPasswordIn,
    LoginIn,
    MeOut,
    ProfileOut,
    ResendCodeIn,
    ResetPasswordIn,
    SignupIn,
    SyncProfileIn,
    TokenOut,
    VerifyEmailIn,
)
from answer_eval.core.security import (
    create_access_token,
    generate_otp,
    generate_secure_token,
    hash_password,
    verify_password,
)
from answer_eval.db.repositories import profiles as profiles_repo
from answer_eval.db.repositories import users as users_repo
from answer_eval.services.mailer import send_password_reset_email, send_verification_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, request: Request):
    """Register a new teacher account and dispatch automated verification email."""
    database = require_database(request)
    email = body.email.lower().strip()

    existing_user = await users_repo.get_user_by_email(database.pool, email)
    otp_code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    if existing_user:
        if existing_user.get("is_verified"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists. Please sign in.",
            )
        # Resend code for unverified account and sync password/profile preferences
        await users_repo.update_verification_code(database.pool, email, otp_code, expires_at)
        hashed_pw = hash_password(body.password)
        await users_repo.update_password(database.pool, str(existing_user["id"]), hashed_pw)
        await profiles_repo.ensure_profile(
            database.pool,
            user_id=str(existing_user["id"]),
            email=email,
            full_name=body.name.strip(),
            department_ids=body.department_ids,
            subjects=body.subjects,
        )
    else:
        hashed_pw = hash_password(body.password)
        new_user = await users_repo.create_user(
            database.pool,
            email=email,
            hashed_password=hashed_pw,
            verification_code=otp_code,
            verification_expires_at=expires_at,
        )
        # Initialize profile record linked to user
        await profiles_repo.ensure_profile(
            database.pool,
            user_id=str(new_user["id"]),
            email=email,
            full_name=body.name.strip(),
            department_ids=body.department_ids,
            subjects=body.subjects,
        )

    # Dispatch email using SMTP App Password (non-blocking in thread pool)
    try:
        import asyncio
        asyncio.create_task(asyncio.to_thread(send_verification_email, email, otp_code, body.name.strip()))
    except Exception as exc:
        logger.warning("Background email dispatch schedule warning: %s", exc)

    return {
        "needs_email_verification": True,
        "email": email,
        "otp_code": otp_code,
        "message": f"A 6-digit verification code has been dispatched to {email}. Please verify your account.",
    }


@router.post("/verify-email", response_model=TokenOut)
async def verify_email(body: VerifyEmailIn, request: Request):
    """Verify email with 6-digit OTP code and issue access token."""
    database = require_database(request)
    email = body.email.lower().strip()

    user = await users_repo.verify_user(database.pool, email, body.code.strip())
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code.",
        )

    profile = await profiles_repo.get_profile(database.pool, str(user["id"]))
    if not profile:
        profile = await profiles_repo.ensure_profile(database.pool, user_id=str(user["id"]), email=email)

    token = create_access_token({
        "sub": str(user["id"]),
        "email": email,
        "full_name": profile.get("full_name", ""),
        "department_ids": profile.get("department_ids", []),
        "subjects": profile.get("subjects", []),
    })

    return TokenOut(access_token=token, token_type="bearer", user=ProfileOut.of(profile))


@router.post("/resend-code")
async def resend_code(body: ResendCodeIn, request: Request):
    """Resend a fresh 6-digit verification OTP."""
    database = require_database(request)
    email = body.email.lower().strip()

    user = await users_repo.get_user_by_email(database.pool, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if user.get("is_verified"):
        return {"message": "Account is already verified. Please sign in."}

    otp_code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    await users_repo.update_verification_code(database.pool, email, otp_code, expires_at)

    profile = await profiles_repo.get_profile(database.pool, str(user["id"]))
    teacher_name = profile.get("full_name", "") if profile else ""
    try:
        import asyncio
        asyncio.create_task(asyncio.to_thread(send_verification_email, email, otp_code, teacher_name))
    except Exception as exc:
        logger.warning("Background email dispatch schedule warning: %s", exc)

    return {"message": f"New verification code dispatched to {email}.", "otp_code": otp_code}


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request):
    """Authenticate teacher credentials and return JWT token."""
    database = require_database(request)
    email = body.email.lower().strip()

    user = await users_repo.get_user_by_email(database.pool, email)
    if not user or not verify_password(body.password, user.get("hashed_password", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.get("is_verified"):
        # Auto-resend verification code
        otp_code = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        await users_repo.update_verification_code(database.pool, email, otp_code, expires_at)
        profile = await profiles_repo.get_profile(database.pool, str(user["id"]))
        send_verification_email(email, otp_code, profile.get("full_name", "") if profile else "")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not yet verified. A fresh verification code has been sent to your email.",
        )

    profile = await profiles_repo.get_profile(database.pool, str(user["id"]))
    if not profile:
        profile = await profiles_repo.ensure_profile(database.pool, user_id=str(user["id"]), email=email)

    token = create_access_token({
        "sub": str(user["id"]),
        "email": email,
        "full_name": profile.get("full_name", ""),
        "department_ids": profile.get("department_ids", []),
        "subjects": profile.get("subjects", []),
    })

    return TokenOut(access_token=token, token_type="bearer", user=ProfileOut.of(profile))


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordIn, request: Request):
    """Request a password reset link."""
    database = require_database(request)
    email = body.email.lower().strip()

    user = await users_repo.get_user_by_email(database.pool, email)
    if user:
        reset_token = generate_secure_token()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        await users_repo.set_reset_token(database.pool, email, reset_token, expires_at)
        profile = await profiles_repo.get_profile(database.pool, str(user["id"]))
        teacher_name = profile.get("full_name", "") if profile else ""
        send_password_reset_email(email, reset_token, teacher_name)

    return {"message": "If an account exists for this email, password reset instructions have been dispatched."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordIn, request: Request):
    """Reset password using a reset token."""
    database = require_database(request)
    hashed_pw = hash_password(body.new_password)
    user = await users_repo.reset_password(database.pool, body.token.strip(), hashed_pw)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )
    return {"message": "Password updated successfully. You may now sign in."}


@router.get("/me", response_model=MeOut)
async def me(request: Request, teacher: CurrentTeacher) -> MeOut:
    database = require_database(request)
    row = await profiles_repo.get_profile(database.pool, teacher.user_id)
    return MeOut(profile=ProfileOut.of(row or {}), user_id=teacher.user_id)


@router.post("/sync-profile", response_model=ProfileOut)
async def sync_profile(
    body: SyncProfileIn,
    request: Request,
    teacher: CurrentTeacher,
) -> ProfileOut:
    database = require_database(request)
    row = await profiles_repo.update_profile(
        database.pool,
        teacher.profile_id,
        full_name=body.full_name,
        department_ids=body.department_ids,
        subjects=body.subjects,
    )
    return ProfileOut.of(row or {})
