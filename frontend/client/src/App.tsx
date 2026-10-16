/** STYLE: Measured Softness — routes share one calm, persistent application shell and preserve room for future pages. */
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import { AppShell } from "./components/app/AppShell";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { TeacherProfileProvider, useTeacherProfile } from "./contexts/TeacherProfileContext";
import CompareText from "./pages/CompareText";
import Configure from "./pages/Configure";
import Computers from "./pages/Computers";
import Evaluation from "./pages/Evaluation";
import Auth from "./pages/Auth";
import Analytics from "./pages/Analytics";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import VerifyEmail from "./pages/VerifyEmail";
import Home from "./pages/Home";
import Results from "./pages/Results";
import Settings from "./pages/Settings";
function ProtectedWorkspace({ children }: { children: React.ReactNode }) { const { isAuthenticated, isInitializing } = useTeacherProfile(); const [, setLocation] = useLocation(); useEffect(() => { if (!isInitializing && !isAuthenticated) setLocation("/login"); }, [isAuthenticated, isInitializing, setLocation]); if (isInitializing || !isAuthenticated) return null; return <>{children}</>; }
function AppContent() {
  const [location] = useLocation();
  const [resetSignal, setResetSignal] = useState(0);
  const loginPage = location === "/login";
  const signUpPage = location === "/signup";
  const verifyEmailPage = location.startsWith("/verify-email");
  const forgotPasswordPage = location === "/forgot-password";
  const resetPasswordPage = location === "/reset-password";
  const comparePage = location === "/compare";
  const configurePage = location === "/configure";
  const evaluationPage = location === "/evaluation";
  const analyticsPage = location.startsWith("/analytics");
  const computersPage = location === "/computers";
  const resultsPage = location.startsWith("/results");
  const settingsPage = location === "/settings";

  if (loginPage) return <Auth mode="login" />;
  if (signUpPage) return <Auth mode="signup" />;
  if (verifyEmailPage) return <VerifyEmail />;
  if (forgotPasswordPage) return <ForgotPassword />;
  if (resetPasswordPage) return <ResetPassword />;

  const protectedPage = comparePage || configurePage || evaluationPage || analyticsPage || computersPage || resultsPage || settingsPage;
  const page = resultsPage ? <Results /> : analyticsPage ? <Analytics /> : evaluationPage ? <Evaluation /> : computersPage ? <Computers /> : configurePage ? <Configure /> : comparePage ? <CompareText resetSignal={resetSignal} /> : settingsPage ? <Settings /> : <Home />;
  return protectedPage ? <ProtectedWorkspace><AppShell onClearComparison={() => setResetSignal((value) => value + 1)}>{page}</AppShell></ProtectedWorkspace> : <AppShell onClearComparison={() => setResetSignal((value) => value + 1)}>{page}</AppShell>;
}
function App() { return <ErrorBoundary><ThemeProvider defaultTheme="light" switchable><TooltipProvider><TeacherProfileProvider><Toaster position="bottom-right" richColors /><AppContent /></TeacherProfileProvider></TooltipProvider></ThemeProvider></ErrorBoundary>; }
export default App;
