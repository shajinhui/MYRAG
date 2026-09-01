import { memo } from "react";
import { FileText, Database, Image, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RAGStats } from "@/types";

interface StatsBarProps {
  stats: RAGStats | undefined;
  processingCount?: number;
}

function StatItem({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof FileText;
  label: string;
  value: number | string;
  accent?: boolean;
}) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Icon className={cn("h-3.5 w-3.5 flex-shrink-0", accent ? "text-primary" : "text-muted-foreground")} />
      <span className="truncate text-[11px] text-muted-foreground">{label}</span>
      <span className={cn("ml-auto text-[11px] font-semibold tabular-nums", accent ? "text-primary" : "text-foreground")}>
        {value}
      </span>
    </div>
  );
}

export const StatsBar = memo(function StatsBar({ stats, processingCount = 0 }: StatsBarProps) {
  if (!stats) return null;

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl border bg-muted/20 px-2.5 py-2">
      <StatItem icon={FileText} label="文档" value={stats.total_documents} />
      <StatItem icon={Database} label="已索引" value={stats.indexed_documents} accent />
      <StatItem icon={Database} label="分块" value={stats.total_chunks} />
      {(stats.image_count ?? 0) > 0 && (
        <StatItem icon={Image} label="图片" value={stats.image_count!} />
      )}

      {processingCount > 0 && (
        <div className="col-span-2 flex items-center gap-1.5 border-t pt-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
          <span className="truncate text-[11px] font-medium text-amber-400">
            正在处理 {processingCount} 个文档...
          </span>
        </div>
      )}
    </div>
  );
});
