/**
 * 确认对话框组件
 * ========================
 *
 * 替代 window.confirm() 的带样式确认对话框。
 * 支持自定义标题、消息和按钮文字。
 */

import { memo, useCallback, useEffect, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";
import { FADE_ENTER, FADE_REDUCED } from "@/lib/motion";

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "default";
}

export const ConfirmDialog = memo(function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title = "确认",
  message,
  confirmLabel = "确认",
  cancelLabel = "取消",
  variant = "default",
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const reduceMotion = useReducedMotion();

  // 打开时聚焦取消按钮
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => cancelRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

  // Escape 关闭；Tab 保持在对话框内循环。
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;

      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable?.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [onCancel]
  );

  return (
    <AnimatePresence
      onExitComplete={() => {
        previousFocusRef.current?.focus();
        previousFocusRef.current = null;
      }}
    >
      {open && (
        <motion.div
          key="confirm-dialog"
          className="fixed inset-0 z-50 flex items-center justify-center"
          initial="closed"
          animate="open"
          exit="closed"
          onKeyDown={handleKeyDown}
        >
          {/* 背景遮罩 */}
          <motion.div
            className="app-dialog-backdrop absolute inset-0 bg-black/55 backdrop-blur-sm"
            variants={{
              closed: { opacity: 0 },
              open: { opacity: 1 },
            }}
            transition={reduceMotion ? FADE_REDUCED : FADE_ENTER}
            onClick={onCancel}
          />

          {/* 对话框 */}
          <motion.div
            ref={dialogRef}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-message"
            className="app-dialog-panel relative z-10 mx-4 w-full max-w-md overflow-hidden rounded-2xl border border-border/80 bg-card shadow-2xl"
            variants={{
              closed: reduceMotion
                ? { opacity: 0 }
                : { opacity: 0, scale: 0.96, y: 4 },
              open: { opacity: 1, scale: 1, y: 0 },
            }}
            transition={reduceMotion ? FADE_REDUCED : FADE_ENTER}
          >
            <div className="p-6">
              {/* 图标 + 标题 */}
              <div className="flex items-start gap-4">
                <div
                  className={cn(
                    "flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center",
                    variant === "danger"
                      ? "bg-destructive/15"
                      : "bg-primary/15"
                  )}
                >
                  <AlertTriangle
                    className={cn(
                      "w-5 h-5",
                      variant === "danger" ? "text-destructive" : "text-primary"
                    )}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <h3
                    id="confirm-title"
                    className="text-lg font-semibold leading-tight"
                  >
                    {title}
                  </h3>
                  <p
                    id="confirm-message"
                    className="mt-2 text-sm text-muted-foreground leading-relaxed"
                  >
                    {message}
                  </p>
                </div>
              </div>
            </div>

            {/* 操作按钮 */}
            <div className="flex justify-end gap-3 px-6 py-4 border-t border-border/50 bg-muted/20">
              <Button
                ref={cancelRef}
                variant="ghost"
                size="sm"
                onClick={onCancel}
              >
                {cancelLabel}
              </Button>
              <Button
                variant={variant === "danger" ? "destructive" : "default"}
                size="sm"
                onClick={onConfirm}
              >
                {confirmLabel}
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
});
