/** STYLE: EvalAI email verification — OTP input with instant activation. */
import { ArrowLeft, CheckCircle2, Mail, RefreshCw, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import { useTeacherProfile } from "@/contexts/TeacherProfileContext";
import { resendVerificationCode } from "@/lib/auth";

export default function VerifyEmail() {
  const [, setLocation] = useLocation();
  const { verifyTeacherEmail } = useTeacherProfile();

  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    try {
      const searchParams = new URLSearchParams(window.location.search);
      const emailParam = searchParams.get("email");
      if (emailParam) setEmail(emailParam);
      const codeParam = searchParams.get("code");
      if (codeParam) setCode(codeParam);
    } catch {}
  }, []);

  const handleVerify = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) {
      setErrorMessage("Enter your email address.");
      return;
    }
    if (!code.trim() || code.trim().length < 6) {
      setErrorMessage("Enter the complete 6-digit verification code.");
      return;
    }

    setSubmitting(true);
    setErrorMessage("");
    try {
      await verifyTeacherEmail(email.trim(), code.trim());
      toast.success("Account verified successfully!", {
        description: "Welcome to EvalAI. Your teacher workspace is ready.",
      });
      setLocation("/");
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Invalid or expired verification code. Please check and try again."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleResend = async () => {
    if (!email.trim()) {
      toast.error("Please enter your email to resend code.");
      return;
    }
    setResending(true);
    try {
      await resendVerificationCode(email.trim());
      toast.success("Verification code resent!", {
        description: `A fresh 6-digit code has been dispatched to ${email.trim()}.`,
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to resend code. Please try again.");
    } finally {
      setResending(false);
    }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#eef0ff] p-5 text-[#171827]">
      <div className="pointer-events-none absolute inset-0 opacity-90 [background-image:radial-gradient(circle_at_12%_15%,rgba(205,214,255,0.74),transparent_23%),radial-gradient(circle_at_85%_80%,rgba(255,235,201,0.5),transparent_25%)]" />

      <section className="relative w-full max-w-[460px] overflow-hidden rounded-[30px] border border-white/85 bg-white/75 p-7 shadow-[0_26px_75px_rgba(63,73,139,0.15)] backdrop-blur-2xl sm:p-9">
        <button
          type="button"
          onClick={() => setLocation("/login")}
          className="inline-flex items-center gap-2 text-[12px] font-semibold text-slate-600 transition-colors hover:text-[#171827]"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to sign in
        </button>

        <div className="mt-8 flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#eff2ff] text-[#6375e6] shadow-[0_4px_12px_rgba(99,117,230,0.15)]">
            <Mail className="h-6 w-6" />
          </span>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[#7788ff]">Automated verification</p>
            <h1 className="text-[24px] font-bold tracking-tight text-[#171827]">Verify Your Email</h1>
          </div>
        </div>

        <p className="mt-4 text-[14px] font-medium leading-relaxed text-slate-600">
          We sent a 6-digit verification code via email to confirm your Teacher Account. Enter it below to activate your evaluation workspace.
        </p>

        <form onSubmit={handleVerify} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-[12px] font-bold text-[#171827]">Teacher email address</span>
            <span className="relative mt-1.5 flex items-center">
              <Mail className="pointer-events-none absolute left-3.5 h-4 w-4 text-[#7788ff]" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teacher@college.edu"
                className="h-12 w-full rounded-2xl border border-[#dfe4ff] bg-white/80 pl-10 pr-3.5 text-[13px] font-semibold text-[#171827] outline-none focus:border-[#7788ff] focus:ring-2 focus:ring-[#b6c0ff]/35"
              />
            </span>
          </label>

          <label className="block">
            <span className="text-[12px] font-bold text-[#171827]">6-Digit verification code (OTP)</span>
            <span className="relative mt-1.5 flex items-center">
              <ShieldCheck className="pointer-events-none absolute left-3.5 h-4 w-4 text-[#7788ff]" />
              <input
                type="text"
                required
                maxLength={8}
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                  setErrorMessage("");
                }}
                placeholder="123456"
                className="h-12 w-full rounded-2xl border border-[#dfe4ff] bg-white/80 pl-10 pr-3.5 font-mono text-[16px] font-bold tracking-widest text-[#171827] outline-none focus:border-[#7788ff] focus:ring-2 focus:ring-[#b6c0ff]/35"
              />
            </span>
          </label>

          {errorMessage && (
            <div className="rounded-xl border border-red-200 bg-red-50/80 p-3 text-[12px] font-semibold text-red-600">
              {errorMessage}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="type-button mt-2 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[#7788ff] px-5 py-3.5 text-[13px] font-bold text-white shadow-[0_10px_24px_rgba(119,136,255,0.34)] transition-all hover:bg-[#6477e8] active:scale-[0.98] disabled:cursor-wait disabled:opacity-70"
          >
            {submitting ? "Verifying code…" : "Verify & Activate Account"}
            <CheckCircle2 className="h-4 w-4" />
          </button>
        </form>

        <div className="mt-6 flex items-center justify-between border-t border-[#e5e9ff] pt-5 text-[12px]">
          <span className="font-medium text-slate-500">Didn't receive the code?</span>
          <button
            type="button"
            disabled={resending}
            onClick={handleResend}
            className="inline-flex items-center gap-1.5 font-bold text-[#687af0] hover:text-[#4f61cf] disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${resending ? "animate-spin" : ""}`} />
            {resending ? "Sending…" : "Resend code"}
          </button>
        </div>

        <p className="mt-5 text-center text-[11px] font-medium text-slate-400">
          Secured by EvalAI PostgreSQL Authentication & Automated Email Verification.
        </p>
      </section>
    </main>
  );
}
