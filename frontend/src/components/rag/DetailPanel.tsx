import { useState, useRef, useCallback, useEffect, type ReactNode } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { FADE_REDUCED, SPRING_SHEET } from "@/lib/motion";

// ---------------------------------------------------------------------------
// useMediaQuery —— 用于响应式断点的简单 Hook
// ---------------------------------------------------------------------------
function useMediaQuery(query: string) {
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query]);
  const [matches, setMatches] = useState(getSnapshot);

  useEffect(() => {
    const mql = window.matchMedia(query);
    setMatches(mql.matches);
    const handler = () => setMatches(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}

// ---------------------------------------------------------------------------
// DetailPanel 组件
// ---------------------------------------------------------------------------
interface DetailPanelProps {
  /** 面板是否可见 */
  open: boolean;
  /** 用户关闭面板时调用 */
  onClose: () => void;
  /** 头部内容（标题 + 标签） */
  header?: ReactNode;
  /** 主要可滚动内容 */
  children: ReactNode;
  /** 面板外层容器的自定义 className */
  className?: string;
}

export function DetailPanel({ open, onClose, header, children, className }: DetailPanelProps) {
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const reduceMotion = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);
  const [panelWidth, setPanelWidth] = useState(45); // 占视口宽度的百分比
  const isDragging = useRef(false);

  // ---- 拖拽调整宽度（仅桌面端） ----
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;

    const handleMouseMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newWidth = ((window.innerWidth - ev.clientX) / window.innerWidth) * 100;
      setPanelWidth(Math.min(70, Math.max(30, newWidth)));
    };

    const handleMouseUp = () => {
      isDragging.current = false;
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, []);

  // ---- 按 Escape 关闭 ----
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // ---- 桌面端：侧边面板 ----
  if (isDesktop) {
    return (
      <AnimatePresence>
        {open && (
          <motion.div
            ref={panelRef}
            initial={reduceMotion ? { opacity: 0 } : { x: "100%", opacity: 0.92 }}
            animate={reduceMotion ? { opacity: 1 } : { x: 0, opacity: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { x: "100%", opacity: 0.92 }}
            transition={reduceMotion ? FADE_REDUCED : SPRING_SHEET}
            style={{ width: `${panelWidth}vw` }}
            role="region"
            aria-label="详情面板"
            className={cn(
              "fixed top-0 right-0 h-full z-40",
              "bg-card border-l shadow-2xl",
              "flex flex-col",
              className
            )}
          >
            {/* 调整宽度手柄 */}
            <div
              onMouseDown={handleMouseDown}
              className="absolute bottom-0 left-0 top-0 z-50 w-1 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50"
              role="separator"
              aria-label="调整详情面板宽度"
            />

            {/* 头部栏 */}
            <div className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0">
              <div className="flex-1 min-w-0">{header}</div>
              <button
                onClick={onClose}
                className="app-icon-button ml-2 h-8 w-8 flex-shrink-0"
                title="关闭面板（Esc）"
                aria-label="关闭详情面板"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 内容 */}
            <div className="flex-1 overflow-y-auto overflow-x-hidden">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    );
  }

  // ---- 移动端：全屏弹窗 ----
  return (
    <AnimatePresence>
      {open && (
        <>
          {/* 背景遮罩 */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={FADE_REDUCED}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* 弹窗 */}
          <motion.div
            initial={reduceMotion ? { opacity: 0 } : { y: "100%", opacity: 0.94 }}
            animate={reduceMotion ? { opacity: 1 } : { y: 0, opacity: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { y: "100%", opacity: 0.94 }}
            transition={reduceMotion ? FADE_REDUCED : SPRING_SHEET}
            role="dialog"
            aria-modal="true"
            aria-label="详情面板"
            className={cn(
              "fixed inset-x-0 bottom-0 top-12 z-50",
              "bg-background rounded-t-xl shadow-2xl",
              "flex flex-col",
              className
            )}
          >
            {/* 头部栏 */}
            <div className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0">
              <div className="flex-1 min-w-0">{header}</div>
              <button
                onClick={onClose}
                className="app-icon-button ml-2 h-8 w-8 flex-shrink-0"
                aria-label="关闭详情面板"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 内容 */}
            <div className="flex-1 overflow-y-auto overflow-x-hidden">
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
