import { memo, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { ChevronRight, Cpu, Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

interface ConfigStatus {
  llm_provider: string;
  llm_model: string;
  kg_embedding_provider: string;
  kg_embedding_model: string;
  kg_embedding_dimension: number;
  myrag_embedding_model: string;
  myrag_reranker_model: string;
}

interface TopBarProps {
  actions?: React.ReactNode;
  className?: string;
}

export const TopBar = memo(function TopBar({ actions, className }: TopBarProps) {
  const location = useLocation();
  const [config, setConfig] = useState<ConfigStatus | null>(null);

  useEffect(() => {
    api.get<ConfigStatus>("/config/status").then(setConfig).catch(() => {});
  }, []);

  const segments: { label: string; active: boolean }[] = [
    { label: "MYRAG", active: false },
  ];

  if (location.pathname === "/") {
    segments.push({ label: "知识库", active: true });
  } else if (location.pathname.startsWith("/knowledge-bases/")) {
    segments.push({ label: "工作区", active: true });
  }

  return (
    <header
      className={cn(
        "app-toolbar relative z-20 flex h-14 flex-shrink-0 items-center justify-between gap-4 px-5",
        className
      )}
    >
      {/* 面包屑导航 */}
      <nav aria-label="面包屑" className="flex min-w-0 items-center gap-1.5 text-[13px]">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-1.5 min-w-0">
            {i > 0 && <ChevronRight className="h-3 w-3 flex-shrink-0 text-muted-foreground/55" />}
            <span
              className={cn(
                "truncate",
                seg.active
                  ? "font-semibold tracking-[-0.01em] text-foreground"
                  : "font-medium text-muted-foreground"
              )}
              aria-current={seg.active ? "page" : undefined}
            >
              {seg.label}
            </span>
          </div>
        ))}
      </nav>

      {/* 右侧：模型徽章 + 操作 */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {config && (
          <div className="hidden items-center gap-1.5 lg:flex">
            <div
              className={cn(
                "app-status-pill flex max-w-44 items-center gap-1.5",
                config.llm_provider === "ollama"
                  ? "text-primary"
                  : "text-sky-500"
              )}
              title={`LLM：${config.llm_provider} / ${config.llm_model}`}
            >
              <Cpu className="w-3 h-3" />
              <span className="truncate">{config.llm_model}</span>
            </div>
            <div
              className="app-status-pill flex max-w-44 items-center gap-1.5 text-violet-500"
              title={`KG 嵌入：${config.kg_embedding_provider} / ${config.kg_embedding_model}（${config.kg_embedding_dimension} 维）`}
            >
              <Database className="w-3 h-3" />
              <span className="truncate">{config.kg_embedding_model}</span>
            </div>
          </div>
        )}
        {actions}
      </div>
    </header>
  );
});
