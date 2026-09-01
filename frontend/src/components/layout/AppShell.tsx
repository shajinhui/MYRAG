import { useState, useEffect, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const STORAGE_KEY = "sidebar-collapsed";
const AUTO_COLLAPSE_WIDTH = 1440;

export function AppShell() {
  const [userCollapsed, setUserCollapsed] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "true";
  });
  const [autoCollapsed, setAutoCollapsed] = useState(false);

  useEffect(() => {
    const check = () => setAutoCollapsed(window.innerWidth < AUTO_COLLAPSE_WIDTH);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const collapsed = userCollapsed || autoCollapsed;

  const toggleSidebar = useCallback(() => {
    const next = !collapsed;
    setAutoCollapsed(false);
    setUserCollapsed(next);
    localStorage.setItem(STORAGE_KEY, String(next));
  }, [collapsed]);

  return (
    <div className="app-shell h-screen flex overflow-hidden">
      <Sidebar collapsed={collapsed} onToggle={toggleSidebar} />
      <div className="relative z-0 flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="app-main relative flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
