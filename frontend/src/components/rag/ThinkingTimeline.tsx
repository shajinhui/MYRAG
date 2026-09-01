/**
 * ThinkingTimeline —— 展示智能体处理步骤的纵向时间线。
 *
 * 两种模式：
 * - “live” —— 流式输出期间：始终展开，激活步骤显示加载动画
 * - “embedded” —— 完成后：折叠摘要，点击展开
 */

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Lightbulb,
  Search,
  Database,
  PenLine,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentStep, AgentStepType } from "@/types";

// ---------------------------------------------------------------------------
// 步骤配置
// ---------------------------------------------------------------------------

interface StepConfig {
  icon: LucideIcon;
  label: string;
}

const STEP_CONFIG: Record<AgentStepType, StepConfig> = {
  analyzing: { icon: Brain, label: "分析中" },
  understood: { icon: Lightbulb, label: "已理解" },
  retrieving: { icon: Search, label: "搜索中" },
  sources_found: { icon: Database, label: "已找到来源" },
  generating: { icon: PenLine, label: "生成中" },
  done: { icon: CheckCircle2, label: "已完成" },
  error: { icon: AlertCircle, label: "出错" },
};

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

// ---------------------------------------------------------------------------
// LiveTimer —— 每 100 毫秒更新一次激活步骤的耗时
// ---------------------------------------------------------------------------

function LiveTimer({ startTimestamp }: { startTimestamp: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const iv = setInterval(() => setElapsed(Date.now() - startTimestamp), 100);
    return () => clearInterval(iv);
  }, [startTimestamp]);

  return (
    <span className="text-[11px] font-mono tabular-nums text-primary/80">
      {formatMs(elapsed)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ThinkingLogSection —— 可折叠的完整思考日志（嵌入模式，流式输出结束后）
// ---------------------------------------------------------------------------

function ThinkingLogSection({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-1.5">
      <button
        onClick={() => setExpanded((p) => !p)}
        className="flex items-center gap-1 text-[11px] text-muted-foreground/70 hover:text-muted-foreground transition-colors"
      >
        <Brain className="w-2.5 h-2.5" />
        <span>{expanded ? "隐藏" : "显示"}思考日志</span>
        <ChevronDown
          className={cn(
            "w-2.5 h-2.5 transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div
              className={cn(
                "mt-1 ml-1 text-[11px] leading-relaxed text-muted-foreground/80 italic",
                "max-h-[200px] overflow-y-auto scrollbar-none",
                "border-l border-border/40 pl-2",
                "whitespace-pre-wrap break-words",
              )}
            >
              {text}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepNode —— 时间线中的单个步骤
// ---------------------------------------------------------------------------

interface StepNodeProps {
  step: AgentStep;
  isLast: boolean;
  isLive: boolean;
}

function StepNode({ step, isLast, isLive }: StepNodeProps) {
  const config = STEP_CONFIG[step.step];
  const Icon = config.icon;
  const isActive = step.status === "active";
  const isError = step.status === "error";
  const isCompleted = step.status === "completed";

  return (
    <motion.div
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="flex gap-2 relative"
    >
      {/* 垂直连接线 */}
      {!isLast && (
        <div
          className={cn(
            "absolute left-[9px] top-[20px] w-px bottom-0",
            isActive ? "bg-primary/20" : "bg-border/50",
          )}
        />
      )}

      {/* 图标节点 */}
      <div className="relative flex-shrink-0 z-10">
        {isActive ? (
          <div className="w-[18px] h-[18px] rounded-full bg-primary/15 flex items-center justify-center ring-1 ring-primary/30">
            <Loader2 className="w-2.5 h-2.5 animate-spin text-primary" />
          </div>
        ) : isError ? (
          <div className="w-[18px] h-[18px] rounded-full bg-destructive/15 flex items-center justify-center">
            <AlertCircle className="w-2.5 h-2.5 text-destructive" />
          </div>
        ) : step.step === "done" ? (
          <div className="w-[18px] h-[18px] rounded-full bg-emerald-500/15 flex items-center justify-center">
            <CheckCircle2 className="w-2.5 h-2.5 text-emerald-500" />
          </div>
        ) : (
          <div className="w-[18px] h-[18px] rounded-full bg-muted flex items-center justify-center">
            <Icon className="w-2.5 h-2.5 text-muted-foreground/80" />
          </div>
        )}
      </div>

      {/* 内容 */}
      <div className="flex-1 min-w-0 pb-2.5">
        <div className="flex items-center gap-1.5 min-h-[18px]">
          <span
            className={cn(
              "text-xs leading-tight",
              isActive && "text-foreground font-medium",
              isCompleted && step.step !== "done" && "text-muted-foreground",
              step.step === "done" && "text-emerald-500 font-medium",
              isError && "text-destructive font-medium",
            )}
          >
            {step.detail}
          </span>

          <span className="ml-auto flex-shrink-0">
            {isActive && isLive ? (
              <LiveTimer startTimestamp={step.timestamp} />
            ) : step.durationMs != null && step.durationMs > 0 ? (
              <span className="text-[11px] font-mono tabular-nums text-muted-foreground/70">
                {formatMs(step.durationMs)}
              </span>
            ) : null}
          </span>
        </div>

        {/* sources_found 步骤的来源徽章 */}
        {step.sourceBadges && step.sourceBadges.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {step.sourceBadges.map((badge) => (
              <span
                key={badge}
                className="inline-flex items-center px-1 py-0.5 text-[10px] font-mono font-bold rounded bg-primary/10 text-primary/80"
              >
                {badge}
              </span>
            ))}
          </div>
        )}

        {/* 思考文本：流式输出期间由 MessageBubble 中的内联预览负责展示，
            完成后在此显示可折叠日志。 */}
        {step.step === "analyzing" && step.thinkingText && !isActive && (
          <ThinkingLogSection text={step.thinkingText} />
        )}
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// TimelineSummary —— 嵌入模式下的单行折叠摘要
// ---------------------------------------------------------------------------

function buildSummary(steps: AgentStep[]): string {
  const sourcesStep = steps.find((s) => s.step === "sources_found");
  const doneStep = steps.find((s) => s.step === "done");

  const parts: string[] = [];

  if (sourcesStep) {
    let sourceText = `${sourcesStep.sourceCount || 0} 个来源`;
    if (sourcesStep.imageCount) {
      sourceText += ` + ${sourcesStep.imageCount} 张图片`;
    }
    parts.push(sourceText);
  }

  if (doneStep?.durationMs) {
    parts.push(formatMs(doneStep.durationMs));
  } else if (doneStep) {
    // 如果 detail 中有耗时信息则提取
    const match = doneStep.detail.match(/[\d.]+[sm]/);
    if (match) parts.push(match[0]);
  }

  const activeStep = steps.find((s) => s.status === "active");

  if (parts.length === 0) {
    // 仍在进行中，显示激活步骤标签
    if (activeStep) {
      const cfg = STEP_CONFIG[activeStep.step];
      return cfg ? `${cfg.label}...` : "处理中...";
    }
    return "处理完成";
  }
  if (sourcesStep) {
    const suffix = parts[1] ? `，耗时 ${parts[1]}` : activeStep ? "，正在生成..." : "";
    return `找到 ${parts[0]}${suffix}`;
  }
  return `耗时 ${parts[0]}`;
}

// ---------------------------------------------------------------------------
// ThinkingTimeline —— 主导出
// ---------------------------------------------------------------------------

interface ThinkingTimelineProps {
  steps: AgentStep[];
  mode: "live" | "embedded";
  className?: string;
  /** 为 true 时自动折叠时间线（答案开始流式输出时使用）。 */
  autoCollapse?: boolean;
}

export function ThinkingTimeline({
  steps,
  mode,
  className,
  autoCollapse = false,
}: ThinkingTimelineProps) {
  // 直播模式初始为展开；嵌入模式（已完成消息）初始为折叠
  const [expanded, setExpanded] = useState(mode === "live");
  const hasAutoCollapsedRef = useRef(false);
  const prevModeRef = useRef(mode);

  // 未启用 autoCollapse 的直播模式 → 展开
  // 启用 autoCollapse → 折叠一次
  // 模式从直播切换到嵌入 → 保持折叠
  useEffect(() => {
    if (autoCollapse && !hasAutoCollapsedRef.current) {
      hasAutoCollapsedRef.current = true;
      setExpanded(false);
    }
  }, [autoCollapse]);

  // 当模式从直播切换到嵌入（流式输出结束）时，
  // 保持当前折叠状态 —— 不要重新展开
  useEffect(() => {
    prevModeRef.current = mode;
  }, [mode]);

  if (steps.length === 0) return null;

  // 折叠摘要 —— 样式类似 ThinkingPanel 头部，便于识别
  const isStillActive = steps.some((s) => s.status === "active");
  if (!expanded) {
    return (
      <div className={cn("rounded-md border border-border/60 bg-background overflow-hidden", className)}>
        <button
          onClick={() => setExpanded(true)}
          className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-primary/80 hover:text-primary transition-colors"
        >
          {isStillActive ? (
            <Loader2 className="w-3 h-3 animate-spin text-primary/80 flex-shrink-0" />
          ) : (
            <CheckCircle2 className="w-3 h-3 text-emerald-500/80 flex-shrink-0" />
          )}
          <span className="flex-1 text-left">{buildSummary(steps)}</span>
          <ChevronDown className="w-3 h-3 flex-shrink-0" />
        </button>
      </div>
    );
  }

  // 展开状态 —— 嵌入模式下用带样式的容器包裹
  const isEmbedded = mode === "embedded" || autoCollapse;

  return (
    <div
      className={cn(
        "relative",
        isEmbedded && "rounded-md border border-border/60 bg-background overflow-hidden",
        className,
      )}
    >
      {/* 嵌入模式下的头部 / 折叠按钮 */}
      {isEmbedded && (
        <button
          onClick={() => setExpanded(false)}
          className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-primary/80 hover:text-primary transition-colors border-b border-border/40"
        >
          <CheckCircle2 className="w-3 h-3 text-emerald-500/80 flex-shrink-0" />
          <span className="flex-1 text-left">{buildSummary(steps)}</span>
          <ChevronDown className="w-3 h-3 flex-shrink-0 rotate-180" />
        </button>
      )}

      <div className={cn(isEmbedded && "px-2.5 py-2")}>
        <AnimatePresence mode="popLayout">
          {steps.map((step, i) => (
            <StepNode
              key={step.id}
              step={step}
              isLast={i === steps.length - 1}
              isLive={mode === "live"}
            />
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
