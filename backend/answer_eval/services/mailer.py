"""Automated email delivery service using SMTP App Password.

Designed for automated verification emails upon Teacher registration and password
resets, with support for Google App Passwords and standard SMTP relays.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", f"EvalAI <{SMTP_USER}>" if SMTP_USER else "EvalAI <no-reply@evalai.internal>")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")


def is_smtp_configured() -> bool:
    user = (SMTP_USER or "").strip().lower()
    pwd = (SMTP_PASSWORD or "").strip()
    if not user or not pwd:
        return False
    if "your_email" in user or "example.com" in user or "xxxx" in pwd:
        return False
    return True


def send_email(to_email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Send an email using SMTP with App Password."""
    if not is_smtp_configured():
        logger.info(
            "SMTP credentials not configured or set to placeholder. Email simulated for %s: %s",
            to_email,
            subject,
        )
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=3) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=3) as server:
                server.ehlo()
                if SMTP_USE_TLS:
                    server.starttls()
                    server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())
        logger.info("Successfully sent email to %s: %s", to_email, subject)
        return True
    except Exception as exc:
        logger.warning("SMTP delivery failed for %s via %s:%s (%s). Falling back to console dispatch.", to_email, SMTP_HOST, SMTP_PORT, exc)
        return False


def send_verification_email(to_email: str, code: str, teacher_name: str = "") -> bool:
    """Send teacher account verification email with a 6-digit OTP code."""
    greeting = f"Hello {teacher_name}," if teacher_name else "Hello,"
    subject = f"EvalAI — Verify Your Teacher Account (Code: {code})"

    text_body = f"""{greeting}

Welcome to EvalAI — AI-Powered Answer Paper Evaluation System.

Your 6-digit verification code to activate your Teacher Account is:

    {code}

This code expires in 15 minutes. Please enter it in the verification screen to activate your workspace.

If you did not request this account, please disregard this email.

— The EvalAI Team
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6fc; margin: 0; padding: 24px; color: #1e293b; }}
    .container {{ max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 20px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }}
    .header {{ background: linear-gradient(135deg, #4f46e5, #7c3aed); padding: 32px 28px; text-align: center; color: #ffffff; }}
    .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }}
    .header p {{ margin: 6px 0 0 0; opacity: 0.85; font-size: 13px; }}
    .content {{ padding: 32px 28px; }}
    .code-box {{ margin: 24px 0; background: #f8fafc; border: 2px dashed #6366f1; border-radius: 14px; padding: 20px; text-align: center; }}
    .code {{ font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #4338ca; font-family: monospace; }}
    .footer {{ padding: 20px 28px; border-top: 1px solid #f1f5f9; font-size: 12px; color: #64748b; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>EvalAI Teacher Workspace</h1>
      <p>Automated Paper Evaluation System</p>
    </div>
    <div class="content">
      <p style="font-size: 15px; font-weight: 600;">{greeting}</p>
      <p style="font-size: 14px; line-height: 1.6; color: #475569;">
        Thank you for joining EvalAI. To complete your Teacher Account setup and begin managing assessments and question papers, please enter the verification code below:
      </p>
      <div class="code-box">
        <div class="code">{code}</div>
      </div>
      <p style="font-size: 13px; color: #64748b; line-height: 1.5;">
        This code is valid for 15 minutes. For your security, do not share this code with anyone.
      </p>
    </div>
    <div class="footer">
      Sent automatically by EvalAI. If you did not create an account, you can safely ignore this email.
    </div>
  </div>
</body>
</html>"""

    # Always log the verification code for immediate developer convenience
    logger.info("VERIFICATION CODE FOR %s: %s", to_email, code)
    print(f"\n[EVALAI MAIL DISPATCH] >>> Verification code for {to_email}: {code} <<<\n", flush=True)

    return send_email(to_email, subject, html_body, text_body)


def send_password_reset_email(to_email: str, reset_token: str, teacher_name: str = "") -> bool:
    """Send password reset email with reset token."""
    greeting = f"Hello {teacher_name}," if teacher_name else "Hello,"
    subject = "EvalAI — Password Reset Request"

    text_body = f"""{greeting}

We received a request to reset your EvalAI account password.

Your reset token is:
{reset_token}

This token will expire in 30 minutes.

— The EvalAI Team
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; background: #f8fafc; padding: 24px;">
  <div style="max-width: 480px; margin: 0 auto; background: white; padding: 28px; border-radius: 16px; border: 1px solid #e2e8f0;">
    <h2 style="color: #4338ca; margin-top: 0;">Password Reset Request</h2>
    <p>{greeting}</p>
    <p>We received a request to reset your password. Use the token below to update your password:</p>
    <div style="background: #f1f5f9; padding: 12px; border-radius: 8px; font-family: monospace; word-break: break-all; margin: 16px 0;">
      {reset_token}
    </div>
    <p style="color: #64748b; font-size: 13px;">This token expires in 30 minutes. If you did not request this, you may ignore this message.</p>
  </div>
</body>
</html>"""

    logger.info("PASSWORD RESET TOKEN FOR %s: %s", to_email, reset_token)
    print(f"\n[EVALAI MAIL DISPATCH] >>> Password reset token for {to_email}: {reset_token} <<<\n", flush=True)

    return send_email(to_email, subject, html_body, text_body)
