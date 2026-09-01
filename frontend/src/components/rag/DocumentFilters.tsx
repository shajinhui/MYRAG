import { memo } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { DocumentStatus } from "@/types";

type FilterStatus = "all" | DocumentStatus;

const TABS: { value: FilterStatus; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "indexed", label: "已索引" },
  { value: "parsing", label: "处理中" },
  { value: "failed", label: "失败" },
];

interface DocumentFiltersProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  statusFilter: FilterStatus;
  onStatusChange: (s: FilterStatus) => void;
  counts: Record<FilterStatus, number>;
}

export type { FilterStatus };

export const DocumentFilters = memo(function DocumentFilters({
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusChange,
  counts,
}: DocumentFiltersProps) {
  return (
    <div className="space-y-2">
      {/* 搜索 */}
      <div className="relative w-full">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="按名称筛选..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-8 h-8 text-sm"
        />
      </div>

      {/* 状态标签 */}
      <div className="grid grid-cols-4 gap-0.5 rounded-xl bg-muted/40 p-0.5" role="tablist" aria-label="文档状态">
        {TABS.map((tab) => {
          const isActive = statusFilter === tab.value;
          // 将处理中的状态合并到“处理中”标签
          let count = counts[tab.value] ?? 0;
          if (tab.value === "parsing") {
            count = (counts.parsing ?? 0) + (counts.indexing ?? 0) + (counts.processing ?? 0);
          }
          return (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onStatusChange(tab.value)}
              className={cn(
                "min-w-0 rounded-[9px] px-1.5 py-1.5 text-[10px] font-medium transition-colors",
                isActive
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {tab.label}
              {count > 0 && (
                <span className={cn(
                  "ml-0.5 text-[9px] tabular-nums",
                  isActive ? "text-primary" : "text-muted-foreground/60"
                )}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
});
