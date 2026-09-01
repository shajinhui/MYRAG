/**
 * 主题切换组件
 * ======================
 *
 * 太阳/月亮图标按钮，用于在浅色和深色主题之间切换。
 */

import { useEffect } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Sun, Moon } from "lucide-react";
import { useThemeStore } from "@/stores/useThemeStore";
import { EASE_OUT, SPRING_CONTROL } from "@/lib/motion";

export function ThemeToggle() {
  const { theme, toggleTheme } = useThemeStore();
  const reduceMotion = useReducedMotion();

  // 同步 <html> 上的 data-theme 属性
  useEffect(() => {
    const root = document.documentElement;
    // 短暂启用过渡类，实现平滑切换
    root.classList.add("theme-transition");
    root.setAttribute("data-theme", theme);
    const timeout = setTimeout(() => {
      root.classList.remove("theme-transition");
    }, 350);
    return () => clearTimeout(timeout);
  }, [theme]);

  return (
    <motion.button
      type="button"
      onClick={toggleTheme}
      title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
      aria-label={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
      className="app-icon-button relative h-8 w-8 overflow-hidden"
      whileTap={reduceMotion ? undefined : { scale: 0.92 }}
      transition={SPRING_CONTROL}
    >
      <AnimatePresence initial={false} mode="wait">
        <motion.span
          key={theme}
          className="absolute inset-0 flex items-center justify-center"
          initial={reduceMotion ? { opacity: 0 } : { opacity: 0, rotate: -18, scale: 0.8 }}
          animate={{ opacity: 1, rotate: 0, scale: 1 }}
          exit={reduceMotion ? { opacity: 0 } : { opacity: 0, rotate: 18, scale: 0.8 }}
          transition={{ duration: 0.16, ease: EASE_OUT }}
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </motion.span>
      </AnimatePresence>
    </motion.button>
  );
}
