/**
 * STYLE: Reference-led soft glass shell — stable fixed layout with independent content scrolling.
 */
import { ReactNode, useState } from "react";
import { useLocation } from "wouter";
import { AppHeader } from "./AppHeader";
import { Sidebar } from "./Sidebar";

interface AppShellProps {
  children: ReactNode;
  onClearComparison: () => void;
}

export function AppShell({ children, onClearComparison }: AppShellProps) {
  const [location] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const activePage =
    location === "/configure"
      ? "configure"
      : location === "/compare"
      ? "compare"
      : location.startsWith("/results")
      ? "results"
      : location.startsWith("/analytics")
      ? "analytics"
      : location === "/evaluation"
      ? "evaluation"
      : location === "/computers"
      ? "computers"
      : location === "/settings"
      ? "settings"
      : "home";

  return (
    <div className="relative flex h-screen h-dvh w-screen overflow-hidden bg-[linear-gradient(145deg,#dfe3fb_0%,#eef0ff_37%,#f7f8ff_68%,#dfe2fb_100%)] text-[#171827] dark:bg-[#0e101b] dark:text-[#f7f7fb]">
      {/* Background radial gradients */}
      <div className="pointer-events-none fixed inset-0 opacity-80 [background-image:radial-gradient(circle_at_7%_11%,rgba(255,255,255,0.92),transparent_26%),radial-gradient(circle_at_84%_8%,rgba(255,252,233,0.72),transparent_25%),radial-gradient(circle_at_70%_94%,rgba(196,207,255,0.45),transparent_30%),linear-gradient(116deg,transparent_11%,rgba(119,136,255,0.12)_11.1%,transparent_11.3%)] dark:opacity-20" />

      {/* Main Layout Container */}
      <div className="relative flex h-full w-full overflow-hidden">
        {/* Pinned Desktop Sidebar & Mobile Drawer */}
        <Sidebar mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />

        {/* Right Content Column: Fixed Header + Scrollable Main */}
        <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden border-l border-black/[0.12] dark:border-white/[0.08]">
          <AppHeader
            activePage={activePage}
            onOpenNavigation={() => setMobileOpen(true)}
            onClearComparison={onClearComparison}
          />
          <main
            className={`min-w-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-5 lg:p-6 ${
              activePage === "configure" || activePage === "evaluation"
                ? "lg:flex lg:flex-col lg:pb-0"
                : ""
            }`}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
