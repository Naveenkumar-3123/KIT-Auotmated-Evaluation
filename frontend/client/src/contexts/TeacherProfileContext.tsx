/** EvalAI teacher session — Native PostgreSQL/JWT backed auth with the backend profile as
 * source of truth. The public hook surface:
 * teacher, isAuthenticated, createTeacherAccount, loginTeacher, verifyTeacherEmail,
 * updateTeacherProfile, logoutTeacher, availableSubjectsForClass. */
import { createContext, ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";
import { classOptions } from "@/components/teacher/teaching-data";
import { parseSubjectNames } from "@/components/teacher/subject-utils";
import type { ProfileResponse } from "@/api/client";
import { fetchMe, syncProfile, updateProfile } from "@/api/auth";
import {
  currentSession,
  metadataFromSession,
  onAuthStateChange,
  sendPasswordResetEmail,
  signInTeacher,
  signOut,
  signUpTeacher,
  updatePassword,
  verifyEmail,
  type Session,
} from "@/lib/auth";

export interface TeacherProfile { id: string; name: string; email: string; departmentIds: string[]; subjects: string[]; }
export interface TeacherProfileInput { name: string; email: string; departmentIds: string[]; subjects: string[]; }
export interface SignupCredentials extends TeacherProfileInput { password: string; }

interface TeacherProfileContextValue {
  teacher: TeacherProfile | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  createTeacherAccount: (input: SignupCredentials, remember: boolean) => Promise<{ needsConfirmation: boolean; email: string; otpCode?: string }>;
  loginTeacher: (email: string, password: string, remember: boolean) => Promise<boolean>;
  verifyTeacherEmail: (email: string, code: string) => Promise<boolean>;
  updateTeacherProfile: (input: TeacherProfileInput) => Promise<void>;
  changePassword: (newPassword: string) => Promise<void>;
  requestPasswordReset: (email: string) => Promise<void>;
  logoutTeacher: () => Promise<void>;
  availableSubjectsForClass: (className: string) => string[];
}

const TeacherProfileContext = createContext<TeacherProfileContextValue | null>(null);

function profileFromResponse(profile: ProfileResponse): TeacherProfile {
  return { id: profile.id, name: profile.full_name, email: profile.email, departmentIds: profile.department_ids ?? [], subjects: profile.subjects ?? [] };
}

function profileFromSession(session: Session): TeacherProfile {
  const metadata = metadataFromSession(session);
  return { id: session.user.id, name: metadata.fullName || session.user.email?.split("@")[0] || "Teacher", email: session.user.email ?? "", departmentIds: metadata.departmentIds, subjects: metadata.subjects };
}

export function TeacherProfileProvider({ children }: { children: ReactNode }) {
  const [teacher, setTeacher] = useState<TeacherProfile | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const loadToken = useRef(0);

  const loadTeacher = async (session: Session) => {
    const token = ++loadToken.current;
    let next = profileFromSession(session);
    try {
      const me = await fetchMe();
      if (me.profile.full_name || me.profile.department_ids.length || me.profile.subjects.length) {
        next = profileFromResponse(me.profile);
      } else if (next.name || next.departmentIds.length) {
        void syncProfile({ full_name: next.name, department_ids: next.departmentIds, subjects: next.subjects }).catch(() => undefined);
      }
    } catch {
      /* Backend unreachable — keep session-derived profile so the UI works. */
    }
    if (loadToken.current === token) setTeacher(next);
  };

  useEffect(() => {
    let mounted = true;
    const boot = async () => {
      const session = await currentSession().catch(() => null);
      if (!mounted) return;
      if (session) await loadTeacher(session);
      setIsInitializing(false);
    };
    void boot();
    const { data } = onAuthStateChange(({ session }) => {
      if (!mounted) return;
      if (session) void loadTeacher(session);
      else setTeacher(null);
      setIsInitializing(false);
    });
    return () => { mounted = false; data.subscription.unsubscribe(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createTeacherAccount = async (input: SignupCredentials): Promise<{ needsConfirmation: boolean; email: string; otpCode?: string }> => {
    const result = await signUpTeacher({
      email: input.email.trim(),
      password: input.password,
      fullName: input.name.trim(),
      departmentIds: input.departmentIds,
      subjects: parseSubjectNames(input.subjects.join(",")),
    });
    return { needsConfirmation: result.needsEmailConfirmation, email: result.email, otpCode: result.otpCode };
  };

  const loginTeacher = async (email: string, password: string): Promise<boolean> => {
    const session = await signInTeacher(email.trim(), password);
    await loadTeacher(session);
    return true;
  };

  const verifyTeacherEmail = async (email: string, code: string): Promise<boolean> => {
    const session = await verifyEmail(email.trim(), code.trim());
    await loadTeacher(session);
    return true;
  };

  const updateTeacherProfile = async (input: TeacherProfileInput) => {
    const subjects = input.subjects.length ? input.subjects : parseSubjectNames(input.subjects.join(","));
    setTeacher((current) => (current ? { ...current, ...input, subjects } : current));
    try {
      const updated = await updateProfile({ full_name: input.name.trim(), department_ids: input.departmentIds, subjects });
      setTeacher(profileFromResponse(updated));
    } catch {
      /* Local state already reflects the edit; backend sync retried on next login. */
    }
  };

  const changePassword = async (newPassword: string) => updatePassword(newPassword);
  const requestPasswordReset = async (email: string) => sendPasswordResetEmail(email.trim());

  const logoutTeacher = async () => {
    await signOut();
    setTeacher(null);
  };

  const availableSubjectsForClass = (className: string) => {
    const selectedClass = classOptions.find((item) => item.name === className);
    if (!teacher) return [];
    if (selectedClass && !teacher.departmentIds.includes(selectedClass.departmentId)) return [];
    return teacher.subjects;
  };

  const isAuthenticated = Boolean(teacher);
  const value = useMemo(
    () => ({
      teacher,
      isAuthenticated,
      isInitializing,
      createTeacherAccount,
      loginTeacher,
      verifyTeacherEmail,
      updateTeacherProfile,
      changePassword,
      requestPasswordReset,
      logoutTeacher,
      availableSubjectsForClass,
    }),
    [teacher, isAuthenticated, isInitializing],
  );
  return <TeacherProfileContext.Provider value={value}>{children}</TeacherProfileContext.Provider>;
}

export function useTeacherProfile() {
  const context = useContext(TeacherProfileContext);
  if (!context) throw new Error("useTeacherProfile must be used within TeacherProfileProvider");
  return context;
}
