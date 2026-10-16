"""Pydantic response/request models for the API surface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class HealthOut(BaseModel):
    status: str
    database: bool


class ProfileOut(BaseModel):
    id: str
    email: str = ""
    full_name: str = ""
    institution_id: str | None = None
    role: str = "teacher"
    department_ids: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, row: dict[str, Any]) -> ProfileOut:
        return cls(
            id=str(row.get("id", "")),
            email=str(row.get("email") or ""),
            full_name=str(row.get("full_name") or ""),
            institution_id=row.get("institution_id"),
            role=str(row.get("role") or "teacher"),
            department_ids=[str(item) for item in (row.get("department_ids") or [])],
            subjects=[str(item) for item in (row.get("subjects") or [])],
        )


class ProfileUpdateIn(BaseModel):
    full_name: str | None = None
    department_ids: list[str] | None = None
    subjects: list[str] | None = None
    institution_id: str | None = None


class SyncProfileIn(ProfileUpdateIn):
    pass


class MeOut(BaseModel):
    profile: ProfileOut
    user_id: str


# Authentication Models
class SignupIn(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    department_ids: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailIn(BaseModel):
    email: EmailStr
    code: str


class ResendCodeIn(BaseModel):
    email: EmailStr


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: ProfileOut
