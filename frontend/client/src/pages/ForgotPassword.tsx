/** STYLE: EvalAI recovery — password-reset entry backed by Supabase Auth email (delivered via Resend). */
import { ArrowLeft, Mail } from "lucide-react";
import { FormEvent, useState } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import { useTeacherProfile } from "@/contexts/TeacherProfileContext";

export default function ForgotPassword() {
  const [, setLocation] = useLocation();
  const { requestPasswordReset } = useTeacherProfile();
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      toast("Enter a valid email address");
      return;
    }
    setSending(true);
    try {
      await requestPasswordReset(email);
      toast("Reset link sent", { description: `If an account exists for ${email.trim()}, a reset link is on its way.` });
    } catch (error) {
      toast("Could not send reset email", { description: error instanceof Error ? error.message : "Please try again." });
    } finally {
      setSending(false);
    }
  };
  return <main className="flex min-h-screen items-center justify-center bg-[#eef0ff] p-5"><section className="w-full max-w-[440px] rounded-[28px] border border-white/85 bg-white/70 p-6 shadow-[0_24px_60px_rgba(63,73,139,0.15)] backdrop-blur-xl sm:p-8"><button type="button" onClick={() => setLocation("/login")} className="inline-flex items-center gap-2 text-[12px] font-semibold text-slate-600 hover:text-[#171827]"><ArrowLeft className="h-3.5 w-3.5" />Back to log in</button><p className="mt-10 text-[11px] font-bold uppercase tracking-[0.14em] text-[#7788ff]">Account access</p><h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.045em] text-[#171827]">Reset your password.</h1><p className="mt-3 text-[14px] font-medium leading-6 text-slate-500">Enter your work email and we’ll send a secure reset link. The email arrives from your institution’s EvalAI domain.</p><form onSubmit={submit} className="mt-7"><label><span className="text-[12px] font-bold text-[#171827]">Work email</span><span className="relative mt-2 flex items-center"><Mail className="absolute left-3.5 h-4 w-4 text-[#7788ff]" /><input required value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="you@college.edu" className="h-12 w-full rounded-2xl border border-[#dfe4ff] bg-white/80 pl-10 pr-3 text-[13px] font-semibold outline-none focus:border-[#7788ff] focus:ring-2 focus:ring-[#b6c0ff]/35" /></span></label><button disabled={sending} className="type-button mt-5 w-full rounded-2xl bg-[#7788ff] px-4 py-3.5 text-[13px] font-bold text-white shadow-[0_10px_24px_rgba(119,136,255,0.3)] disabled:cursor-wait disabled:opacity-70">{sending ? "Sending…" : "Prepare reset request"}</button></form></section></main>;
}
