/** STYLE: EvalAI recovery — set a new password after following the emailed Supabase reset link. */
import { ArrowLeft, Eye, EyeOff, LockKeyhole, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import { useTeacherProfile } from "@/contexts/TeacherProfileContext";

type Errors = Partial<Record<"password" | "confirmPassword", string>>;

export default function ResetPassword() {
  const [, setLocation] = useLocation();
  const { changePassword } = useTeacherProfile();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Errors>({});

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const next: Errors = {};
    if (!password) next.password = "Enter a new password.";
    else if (password.length < 8) next.password = "Use at least 8 characters.";
    if (password !== confirmPassword) next.confirmPassword = "Passwords do not match.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    setSubmitting(true);
    try {
      await changePassword(password);
      toast("Password updated", { description: "Sign in with your new password to continue." });
      setLocation("/login");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not update the password.";
      toast("Reset link problem", { description: `${message} Request a fresh reset link if it has expired.` });
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-[#eef0ff] p-5"><section className="w-full max-w-[440px] rounded-[28px] border border-white/85 bg-white/70 p-6 shadow-[0_24px_60px_rgba(63,73,139,0.15)] backdrop-blur-xl sm:p-8"><button type="button" onClick={() => setLocation("/login")} className="inline-flex items-center gap-2 text-[12px] font-semibold text-slate-600 hover:text-[#171827]"><ArrowLeft className="h-3.5 w-3.5" />Back to log in</button><p className="mt-10 text-[11px] font-bold uppercase tracking-[0.14em] text-[#7788ff]">Account access</p><h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.045em] text-[#171827]">Choose a new password.</h1><p className="mt-3 text-[14px] font-medium leading-6 text-slate-500">Your reset link was verified automatically. Pick something strong — at least 8 characters.</p><form onSubmit={submit} className="mt-7 space-y-4"><label className="block"><span className="text-[12px] font-bold text-[#171827]">New password</span><span className="relative mt-2 flex items-center"><LockKeyhole className="pointer-events-none absolute left-3.5 h-4 w-4 text-[#7788ff]" /><input value={password} onChange={(event) => setPassword(event.target.value)} type={visible ? "text" : "password"} placeholder="Enter your new password" autoComplete="new-password" className={`h-12 w-full rounded-2xl border bg-white/78 pl-10 pr-11 text-[13px] font-semibold outline-none focus:ring-2 focus:ring-[#b6c0ff]/35 ${errors.password ? "border-[#d97b77]" : "border-[#dfe4ff] focus:border-[#7788ff]"}`} /><button type="button" aria-label={visible ? "Hide password" : "Show password"} onClick={() => setVisible((value) => !value)} className="absolute right-2.5 rounded-xl p-2 text-slate-400 hover:bg-[#f2f4ff] hover:text-[#5d70dc]">{visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></span>{errors.password && <p className="mt-1.5 text-[11px] font-semibold text-[#b85d59]">{errors.password}</p>}</label><label className="block"><span className="text-[12px] font-bold text-[#171827]">Confirm new password</span><span className="relative mt-2 flex items-center"><ShieldCheck className="pointer-events-none absolute left-3.5 h-4 w-4 text-[#7788ff]" /><input value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} type={visible ? "text" : "password"} placeholder="Repeat your new password" autoComplete="new-password" className={`h-12 w-full rounded-2xl border bg-white/78 pl-10 pr-3.5 text-[13px] font-semibold outline-none focus:ring-2 focus:ring-[#b6c0ff]/35 ${errors.confirmPassword ? "border-[#d97b77]" : "border-[#dfe4ff] focus:border-[#7788ff]"}`} /></span>{errors.confirmPassword && <p className="mt-1.5 text-[11px] font-semibold text-[#b85d59]">{errors.confirmPassword}</p>}</label><button disabled={submitting} className="type-button w-full rounded-2xl bg-[#7788ff] px-4 py-3.5 text-[13px] font-bold text-white shadow-[0_10px_24px_rgba(119,136,255,0.3)] disabled:cursor-wait disabled:opacity-70">{submitting ? "Updating…" : "Set new password"}</button></form></section></main>;
}
