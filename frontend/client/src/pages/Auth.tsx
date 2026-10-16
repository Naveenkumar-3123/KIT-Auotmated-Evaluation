/** STYLE: EvalAI public access — periwinkle action hierarchy, source-sheet evidence artifacts, and a compact scanning companion make account setup feel part of the assessment studio. */
import {
  ArrowLeft, ArrowRight, Check, Eye, EyeOff, FileCheck2, FileSearch2,
  LockKeyhole, Mail, ScanLine, UserRound,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import { CommaSeparatedSubjectsField } from "@/components/teacher/CommaSeparatedSubjectsField";
import { TeachingMultiSelect } from "@/components/teacher/TeachingMultiSelect";
import { departmentOptions } from "@/components/teacher/teaching-data";
import { parseSubjectNames } from "@/components/teacher/subject-utils";
import { useTeacherProfile } from "@/contexts/TeacherProfileContext";

const markUrl = "/manus-storage/ocr-mark_cbb7933a.png";
const botUrl = "/manus-storage/evalbot-guide_70c167ba.png";
type Errors = Partial<Record<"name" | "email" | "password" | "confirmPassword" | "departments" | "subjects", string>>;

export default function Auth({ mode }: { mode: "login" | "signup" }) {
  const [, setLocation] = useLocation();
  const { createTeacherAccount, loginTeacher } = useTeacherProfile();
  const signingUp = mode === "signup";
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [departmentIds, setDepartmentIds] = useState<string[]>([]);
  const [subjectsInput, setSubjectsInput] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const updateDepartments = (ids: string[]) => {
    setDepartmentIds(ids);
    setErrors((current) => ({ ...current, departments: undefined, subjects: undefined }));
  };
  const validate = () => {
    const next: Errors = {};
    if (signingUp && !name.trim()) next.name = "Enter your full name.";
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = "Enter a valid email address.";
    if (!password) next.password = "Enter your password.";
    else if (password.length < 8) next.password = "Use at least 8 characters.";
    if (signingUp && password !== confirmPassword) next.confirmPassword = "Passwords do not match.";
    if (signingUp && !departmentIds.length) next.departments = "Choose at least one department.";
    if (signingUp && !parseSubjectNames(subjectsInput).length) next.subjects = "Enter at least one subject you teach.";
    setErrors(next);
    return Object.keys(next).length === 0;
  };
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validate()) return;
    setSubmitting(true);
    try {
      if (signingUp) {
        const { needsConfirmation, email: createdEmail, otpCode } = await createTeacherAccount({ name: name.trim(), email: email.trim(), password, departmentIds, subjects: parseSubjectNames(subjectsInput) }, remember);
        if (needsConfirmation) {
          toast.success("Verification code dispatched", { description: "We sent a 6-digit code to your email. Enter it below to activate your account." });
          const codeQuery = otpCode ? `&code=${encodeURIComponent(otpCode)}` : "";
          setLocation(`/verify-email?email=${encodeURIComponent(createdEmail || email.trim())}${codeQuery}`);
        } else {
          toast.success("Teacher account created", { description: "Your teaching profile is ready and will personalize Configure." });
          setLocation("/");
        }
      } else {
        await loginTeacher(email, password, remember);
        toast.success("Welcome back", { description: "Your teacher workspace is ready for assessment work." });
        setLocation("/");
      }
    } catch (error: any) {
      if (error?.needsEmailVerification) {
        toast.error("Email not verified", { description: "Please enter the verification code sent to your email." });
        setLocation(`/verify-email?email=${encodeURIComponent(error.email || email.trim())}`);
        return;
      }
      setErrors({ email: error instanceof Error ? error.message : "Authentication failed. Please try again." });
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="relative min-h-screen overflow-hidden bg-[#eef0ff] px-4 py-5 text-[#171827] sm:px-7 sm:py-8">
    <div className="pointer-events-none absolute inset-0 opacity-90 [background-image:radial-gradient(circle_at_12%_15%,rgba(205,214,255,0.74),transparent_23%),radial-gradient(circle_at_85%_80%,rgba(255,235,201,0.5),transparent_25%),linear-gradient(121deg,transparent_28%,rgba(119,136,255,0.08)_28.1%,transparent_28.35%)]" />
    <section className="relative mx-auto grid min-h-[calc(100vh-40px)] max-w-[1180px] overflow-hidden rounded-[30px] border border-white/85 bg-white/62 shadow-[0_26px_75px_rgba(63,73,139,0.15)] backdrop-blur-2xl lg:grid-cols-[0.92fr_1.08fr]">
      <aside className="relative hidden overflow-hidden border-r border-white/70 bg-[linear-gradient(145deg,rgba(241,244,255,0.88),rgba(255,255,255,0.55))] px-10 py-10 lg:block">
        <div className="pointer-events-none absolute inset-0 opacity-70 [background-image:radial-gradient(circle_at_17%_19%,rgba(151,166,255,0.3),transparent_22%),linear-gradient(118deg,transparent_38%,rgba(119,136,255,0.1)_38.2%,transparent_38.45%)]" />
        <div className="pointer-events-none absolute left-10 top-[122px] h-16 w-16 border-l border-t-2 border-[#8b9aff]/65" />
        <div className="pointer-events-none absolute bottom-[82px] right-9 h-24 w-24 border-b border-r-2 border-[#8b9aff]/50" />
        <button type="button" onClick={() => setLocation("/")} className="relative inline-flex items-center gap-2 text-[12px] font-semibold text-slate-600 transition-colors hover:text-[#171827] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#7788ff]"><ArrowLeft className="h-3.5 w-3.5" />Back to EvalAI</button>
        <div className="relative mt-16 max-w-[360px]">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#cfd8ff] bg-white/78 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.13em] text-[#6174e8]"><ScanLine className="h-3.5 w-3.5" />Assessment evidence</div>
          <h1 className="mt-5 text-[38px] font-semibold leading-[1.02] tracking-[-0.055em] text-[#171827]">{signingUp ? <>Set the context for every <span className="text-[#7788ff]">question-paper review.</span></> : <>Return to answer evidence and <span className="text-[#7788ff]">teacher review.</span></>}</h1>
          <p className="mt-5 max-w-[325px] text-[15px] font-medium leading-6 text-slate-600">{signingUp ? "Your departments and subjects keep question-paper evidence, marking policy, and evaluation setup relevant from the first assessment." : "Continue checking answer capture, applying marking policy, and preserving every teacher decision."}</p>
        </div>
        <div className="relative mt-8 h-[346px] overflow-hidden">
          <div className="absolute left-5 right-3 top-[42%] h-px bg-[linear-gradient(90deg,transparent,rgba(119,136,255,0.72),transparent)]" />
          <div className="absolute right-9 top-[36%] h-3 w-3 rounded-full border-2 border-white bg-[#7788ff] shadow-[0_0_0_4px_rgba(119,136,255,0.15)]" />
          <EvidenceTile />
          <div className="ocr-focus-frame absolute bottom-1 left-[57%] h-[278px] w-[274px] -translate-x-1/2 overflow-hidden">
            <img src={botUrl} alt="EvalBot holding an assessment checklist beside source-sheet evidence" className="absolute bottom-0 left-1/2 h-[278px] w-[278px] -translate-x-1/2 object-contain mix-blend-multiply drop-shadow-[0_22px_28px_rgba(56,65,125,0.2)]" />
          </div>
          <div className="absolute bottom-8 left-0 rounded-2xl border border-white/90 bg-white/95 px-3.5 py-2.5 shadow-[0_12px_28px_rgba(67,76,139,0.13)]">
            <p className="text-[10px] font-bold uppercase tracking-[0.13em] text-[#6679e8]">EvalAI guide</p>
            <p className="mt-1 max-w-[260px] text-[12px] font-semibold leading-4 text-[#171827]">{signingUp ? "Tell me what you teach, and I’ll align your assessment evidence." : "Welcome back! Ready to review another answer sheet?"}</p>
          </div>
        </div>
        <div className="relative flex gap-3 text-[11px] font-semibold text-slate-500"><span className="inline-flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-[#589377]" />Source sheet aligned</span><span className="inline-flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-[#589377]" />Marking context ready</span></div>
      </aside>
      <div className="relative flex min-h-full flex-col px-5 py-6 sm:px-10 sm:py-9 lg:px-14">
        <div className="flex items-center justify-between gap-3"><button type="button" onClick={() => setLocation("/")} className="inline-flex items-center gap-2 rounded-xl p-1 text-[12px] font-semibold text-slate-600 hover:text-[#171827] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#7788ff] lg:hidden"><ArrowLeft className="h-3.5 w-3.5" />Home</button><div className="ml-auto inline-flex items-center gap-2 text-[12px] font-semibold text-slate-500"><span>{signingUp ? "Already using EvalAI?" : "Don’t have an account?"}</span><button type="button" onClick={() => setLocation(signingUp ? "/login" : "/signup")} className="text-[#687af0] hover:text-[#4f61cf] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff]">{signingUp ? "Sign in" : "Create account"}</button></div></div>
        <div className="mt-8 flex flex-1 items-center justify-center lg:mt-0"><div className="w-full max-w-[410px]">
          <BrandBlock />
          <p className="mt-7 text-[11px] font-bold uppercase tracking-[0.14em] text-[#7788ff]">{signingUp ? "Create teacher account" : "Teacher workspace"}</p>
          <h2 className="mt-3 text-[32px] font-semibold leading-[1.05] tracking-[-0.052em] text-[#171827]">{signingUp ? "Set up your evaluation workspace." : "Welcome back."}</h2>
          <p className="mt-3 text-[14px] font-medium leading-6 text-slate-500">{signingUp ? "Register your teaching context so EvalAI prepares the right subjects for every assessment evidence review." : "Sign in to continue managing answer evidence, evaluations, and student results."}</p>
          <form className="mt-7 space-y-4" onSubmit={handleSubmit}>
            {signingUp && <Field label="Full name" value={name} onChange={setName} name="fullName" type="text" placeholder="Dr. Ananya Rao" icon={UserRound} error={errors.name} autoComplete="name" />}
            <Field label="Email address" value={email} onChange={setEmail} name="email" type="email" placeholder="you@college.edu" icon={Mail} error={errors.email} autoComplete="email" />
            <PasswordField value={password} onChange={setPassword} visible={showPassword} onVisibilityChange={() => setShowPassword((value) => !value)} error={errors.password} />
            {signingUp && <PasswordField label="Confirm password" value={confirmPassword} onChange={setConfirmPassword} visible={showPassword} onVisibilityChange={() => setShowPassword((value) => !value)} error={errors.confirmPassword} confirm autoComplete="new-password" />}
            {signingUp && <div className="space-y-4 border-t border-[#e5e9ff] pt-5"><div><p className="text-[11px] font-bold uppercase tracking-[0.13em] text-[#7788ff]">Teaching information</p><p className="mt-1 text-[12px] font-medium text-slate-500">These account-level preferences keep every assessment setup teacher-specific.</p></div><TeachingMultiSelect label="Departments" required options={departmentOptions} selectedIds={departmentIds} onChange={updateDepartments} placeholder="Add department" emptyMessage="No departments match your search." error={errors.departments} /><CommaSeparatedSubjectsField value={subjectsInput} onChange={(value) => { setSubjectsInput(value); setErrors((current) => ({ ...current, subjects: undefined })); }} error={errors.subjects} /></div>}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-1"><label className="inline-flex items-center gap-2 text-[12px] font-medium text-slate-500"><input checked={remember} onChange={(event) => setRemember(event.target.checked)} type="checkbox" className="h-3.5 w-3.5 rounded border-slate-300 accent-[#7788ff]" />Remember me on this device</label>{!signingUp && <button type="button" onClick={() => setLocation("/forgot-password")} className="text-[12px] font-bold text-[#687af0] hover:text-[#4f61cf] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff]">Forgot password?</button>}</div>
            <button disabled={submitting} type="submit" className="type-button mt-2 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[#7788ff] px-5 py-3.5 text-[13px] font-bold text-white shadow-[0_10px_24px_rgba(119,136,255,0.34)] transition-all duration-150 hover:-translate-y-px hover:bg-[#6477e8] active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] disabled:cursor-wait disabled:opacity-70">{submitting ? "Preparing workspace…" : signingUp ? "Create Teacher Account" : "Sign In"}<ArrowRight className="h-4 w-4" /></button>
          </form>
          <p className="mt-5 text-center text-[11px] font-medium leading-5 text-slate-400">Secured by EvalAI PostgreSQL Authentication & Automated Email Verification.</p>
        </div></div>
      </div>
    </section>
  </main>;
}

function BrandBlock() { return <div className="flex items-center gap-3"><span className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-[#bec9ff] bg-white/90 shadow-[0_10px_22px_rgba(90,105,190,0.15)]"><span className="absolute inset-1.5 border-l-2 border-t-2 border-[#7788ff]" /><span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full border-2 border-white bg-[#7788ff]" /><span className="absolute bottom-2 left-2 h-px w-5 bg-[#7788ff]" /><img src={markUrl} alt="EvalAI" className="relative h-8 w-8 object-contain" /></span><div><p className="text-[17px] font-extrabold tracking-[-0.04em] text-[#171827]">EvalAI</p><p className="flex items-center gap-1 text-[11px] font-semibold text-[#6375e6]"><FileCheck2 className="h-3 w-3" />AI Question Paper Evaluation</p></div></div>; }
function EvidenceTile() { return <div className="absolute left-1 top-[48px] w-[166px] rounded-2xl border border-[#d7deff] bg-white/90 p-3 shadow-[0_12px_25px_rgba(67,76,139,0.13)]"><div className="flex items-center justify-between"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#eef1ff] text-[#687af0]"><FileSearch2 className="h-3.5 w-3.5" /></span><span className="flex h-2 w-2 rounded-full bg-[#589377] ring-4 ring-[#dff2e8]" /></div><p className="mt-3 text-[9px] font-bold uppercase tracking-[0.13em] text-[#7183ef]">Source-sheet signal</p><p className="mt-1 text-[11px] font-bold text-[#171827]">Assessment context aligned</p><div className="mt-3 space-y-1"><span className="block h-px w-full bg-[#cbd4ff]" /><span className="block h-px w-[82%] bg-[#dce2ff]" /><span className="block h-px w-[64%] bg-[#dce2ff]" /></div><span className="absolute -bottom-2 right-4 h-4 w-4 border-b-2 border-r-2 border-[#7788ff]/70" /></div>; }
function Field({ label, value, onChange, name, type, placeholder, icon: Icon, error, autoComplete }: { label: string; value: string; onChange: (value: string) => void; name: string; type: string; placeholder: string; icon: typeof Mail; error?: string; autoComplete: string }) { return <label className="block"><span className="text-[12px] font-bold text-[#171827]">{label}</span><span className="relative mt-2 flex items-center"><Icon className="pointer-events-none absolute left-3.5 h-4 w-4 text-[#7788ff]" /><input name={name} value={value} onChange={(event) => onChange(event.target.value)} type={type} placeholder={placeholder} autoComplete={autoComplete} className={`h-12 w-full rounded-2xl border bg-white/78 pl-10 pr-3.5 text-[13px] font-semibold text-[#171827] outline-none transition-colors placeholder:font-medium placeholder:text-slate-400 focus:ring-2 focus:ring-[#b6c0ff]/35 ${error ? "border-[#d97b77] focus:border-[#d97b77]" : "border-[#dfe4ff] focus:border-[#7788ff]"}`} /></span>{error && <p className="mt-1.5 text-[11px] font-semibold text-[#b85d59]">{error}</p>}</label>; }
function PasswordField({ label = "Password", value, onChange, visible, onVisibilityChange, error, confirm = false, autoComplete = "current-password" }: { label?: string; value: string; onChange: (value: string) => void; visible: boolean; onVisibilityChange: () => void; error?: string; confirm?: boolean; autoComplete?: string }) { return <label className="block"><span className="text-[12px] font-bold text-[#171827]">{label}</span><span className="relative mt-2 flex items-center"><LockKeyhole className="pointer-events-none absolute left-3.5 h-4 w-4 text-[#7788ff]" /><input value={value} onChange={(event) => onChange(event.target.value)} type={visible ? "text" : "password"} placeholder={confirm ? "Repeat your password" : "Enter your password"} autoComplete={autoComplete} className={`h-12 w-full rounded-2xl border bg-white/78 pl-10 pr-11 text-[13px] font-semibold text-[#171827] outline-none transition-colors placeholder:font-medium placeholder:text-slate-400 focus:ring-2 focus:ring-[#b6c0ff]/35 ${error ? "border-[#d97b77] focus:border-[#d97b77]" : "border-[#dfe4ff] focus:border-[#7788ff]"}`} /><button type="button" aria-label={visible ? "Hide password" : "Show password"} onClick={onVisibilityChange} className="absolute right-2.5 rounded-xl p-2 text-slate-400 hover:bg-[#f2f4ff] hover:text-[#5d70dc] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff]">{visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></span>{error && <p className="mt-1.5 text-[11px] font-semibold text-[#b85d59]">{error}</p>}</label>; }
