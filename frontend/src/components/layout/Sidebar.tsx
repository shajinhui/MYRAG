import { memo } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Database,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";
import { EASE_OUT, MOTION_INSTANT, SPRING_CONTROL, SPRING_PANEL } from "@/lib/motion";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export const Sidebar = memo(function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: workspaces } = useWorkspaces();
  const reduceMotion = useReducedMotion();

  const activeWorkspaceId = location.pathname.match(/\/knowledge-bases\/(\d+)/)?.[1];
  const isHome = location.pathname === "/";
  const sidebarTransition = reduceMotion ? MOTION_INSTANT : SPRING_PANEL;
  const selectionTransition = reduceMotion ? MOTION_INSTANT : SPRING_CONTROL;

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 64 : 248 }}
      transition={sidebarTransition}
      className="app-sidebar relative z-30 flex h-full flex-shrink-0 flex-col overflow-hidden"
      aria-label="主导航"
      data-collapsed={collapsed || undefined}
    >
      {/* 标志 */}
      <div className="app-chrome-divider flex h-14 flex-shrink-0 items-center gap-2.5 border-b px-3">
        <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-[11px] border border-primary/20 bg-primary/12 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
          <Database className="h-[18px] w-[18px] text-primary" />
        </div>
        {!collapsed && (
          <motion.div
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.16, ease: EASE_OUT }}
            className="min-w-0"
          >
            <p className="truncate text-[13px] font-bold tracking-[0.08em] text-foreground">MYRAG</p>
            <p className="truncate text-[10px] font-medium text-muted-foreground">知识工作台</p>
          </motion.div>
        )}
      </div>

      {/* 导航 */}
      <nav className="flex-shrink-0 space-y-1 px-2.5 pt-3" aria-label="主要页面">
        <button
          onClick={() => navigate("/")}
          className={cn(
            "app-nav-item relative flex h-9 w-full items-center rounded-[10px] text-[13px] font-medium",
            collapsed ? "justify-center px-0" : "gap-2.5 px-2.5",
            isHome && !activeWorkspaceId
              ? "text-foreground"
              : "text-muted-foreground"
          )}
          title={collapsed ? "知识库" : undefined}
          aria-current={isHome && !activeWorkspaceId ? "page" : undefined}
        >
          {isHome && !activeWorkspaceId && (
            <motion.span
              layoutId="sidebar-selection"
              className="absolute inset-0 rounded-[10px] border border-primary/15 bg-primary/12 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
              transition={selectionTransition}
            />
          )}
          <Database className="relative z-10 h-4 w-4 flex-shrink-0" />
          {!collapsed && <span className="relative z-10 truncate">知识库</span>}
        </button>
      </nav>

      {/* 可滚动的工作区列表 */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!collapsed && workspaces && workspaces.length > 0 && (
          <div className="mt-5 px-2.5">
            <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/75">
              工作区
            </p>
            <div className="space-y-1">
              {workspaces.slice(0, 20).map((ws) => {
                const isActive = activeWorkspaceId === String(ws.id);
                return (
                  <button
                    key={ws.id}
                    onClick={() => navigate(`/knowledge-bases/${ws.id}`)}
                    className={cn(
                      "app-nav-item relative flex h-9 w-full items-center gap-2 px-2.5 text-[13px]",
                      isActive
                        ? "font-medium text-foreground"
                        : "text-muted-foreground"
                    )}
                    aria-current={isActive ? "page" : undefined}
                  >
                    {isActive && (
                      <motion.span
                        layoutId="sidebar-selection"
                        className="absolute inset-0 rounded-[10px] border border-primary/15 bg-primary/12 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                        transition={selectionTransition}
                      />
                    )}
                    <Database className="relative z-10 h-3.5 w-3.5 flex-shrink-0" />
                    <span className="relative z-10 truncate">{ws.name}</span>
                    <span className="relative z-10 ml-auto text-[10px] tabular-nums text-muted-foreground/60">
                      {ws.document_count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 折叠状态指示 */}
        {collapsed && (
          <div className="mt-5 space-y-1 px-2.5">
            {workspaces?.slice(0, 6).map((ws) => {
              const isActive = activeWorkspaceId === String(ws.id);
              return (
                <button
                  key={`ws-${ws.id}`}
                  onClick={() => navigate(`/knowledge-bases/${ws.id}`)}
                  className={cn(
                    "app-nav-item relative flex h-9 w-full items-center justify-center rounded-[10px]",
                    isActive
                      ? "text-foreground"
                      : "text-muted-foreground"
                  )}
                  title={ws.name}
                  aria-current={isActive ? "page" : undefined}
                >
                  {isActive && (
                    <motion.span
                      layoutId="sidebar-selection"
                      className="absolute inset-0 rounded-[10px] border border-primary/15 bg-primary/12"
                      transition={selectionTransition}
                    />
                  )}
                  <Database className="relative z-10 h-3.5 w-3.5" />
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* 底部 */}
      <div
        className={cn(
          "app-chrome-divider flex flex-shrink-0 items-center border-t p-2.5",
          collapsed ? "flex-col gap-1" : "justify-between"
        )}
      >
        <ThemeToggle />
        <motion.button
          type="button"
          onClick={onToggle}
          className="app-icon-button h-8 w-8"
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          aria-expanded={!collapsed}
          whileTap={reduceMotion ? undefined : { scale: 0.92 }}
          transition={SPRING_CONTROL}
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <ChevronLeft className="w-4 h-4" />
          )}
        </motion.button>
      </div>
    </motion.aside>
  );
});
