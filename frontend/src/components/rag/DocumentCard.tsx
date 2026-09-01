import { memo, useState, useEffect, useRef } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  FileText,
  FileType,
  Presentation,
  FileCode,
  Hash,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  File,
  Sparkles,
  FileUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { EASE_OUT, MOTION_INSTANT, SPRING_CONTROL } from "@/lib/motion";
import type { Document, DocumentStatus } from "@/types";

// ---------------------------------------------------------------------------
// 文件类型图标映射
// ---------------------------------------------------------------------------
const FILE_TYPE_CONFIG: Record<string, { icon: typeof FileText; color: string }> = {
  pdf:  { icon: FileText, color: "text-red-400" },
  docx: { icon: FileType, color: "text-blue-400" },
  pptx: { icon: Presentation, color: "text-orange-400" },
  txt:  { icon: FileCode, color: "text-muted-foreground" },
  md:   { icon: Hash, color: "text-purple-400" },
};

function getFileConfig(fileType: string) {
  const ext = fileType.replace(".", "").toLowerCase();
  return FILE_TYPE_CONFIG[ext] ?? { icon: File, color: "text-muted-foreground" };
}

// ---------------------------------------------------------------------------
// 状态徽章
// ---------------------------------------------------------------------------
const STATUS_CONFIG: Record<DocumentStatus, { label: string; className: string; icon: typeof CheckCircle2 }> = {
  pending:    { label: "待处理",    className: "bg-muted text-muted-foreground",           icon: Clock },
  parsing:    { label: "解析中",    className: "bg-blue-400/15 text-blue-400",             icon: Loader2 },
  indexing:   { label: "索引中",    className: "bg-amber-400/15 text-amber-400",           icon: Loader2 },
  processing: { label: "处理中",    className: "bg-amber-400/15 text-amber-400",           icon: Loader2 },
  indexed:    { label: "已索引",    className: "bg-primary/15 text-primary",               icon: CheckCircle2 },
  failed:     { label: "失败",      className: "bg-destructive/15 text-destructive",       icon: XCircle },
};

function StatusBadge({ status }: { status: DocumentStatus }) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;
  const Icon = config.icon;
  const isAnimated = status === "parsing" || status === "indexing" || status === "processing";

  return (
    <span className={cn("inline-flex flex-shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium", config.className)}>
      <Icon className={cn("h-2.5 w-2.5", isAnimated && "animate-spin")} />
      {config.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// 元数据标签
// ---------------------------------------------------------------------------
function MetadataChips({ doc }: { doc: Document }) {
  const chips: { label: string; value: number }[] = [];
  if (doc.page_count && doc.page_count > 0) chips.push({ label: "页", value: doc.page_count });
  if (doc.chunk_count > 0) chips.push({ label: "分块", value: doc.chunk_count });
  if (doc.image_count && doc.image_count > 0) chips.push({ label: "图片", value: doc.image_count });
  if (doc.table_count && doc.table_count > 0) chips.push({ label: "表格", value: doc.table_count });

  if (chips.length === 0) return null;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
      {chips.map((c) => (
        <span key={c.label} className="whitespace-nowrap text-[10px] text-muted-foreground">
          {c.value} {c.label}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DocumentCard 组件
// ---------------------------------------------------------------------------
interface DocumentCardProps {
  doc: Document;
  selected?: boolean;
  onDelete: (id: number) => void;
  onReindex: (id: number) => void;
  onProcess: (id: number) => void;
  onReplace: (id: number, file: File) => void;
  isProcessing?: boolean;
  isReplacing?: boolean;
  onClick?: (doc: Document) => void;
}

export const DocumentCard = memo(function DocumentCard({
  doc,
  selected,
  onDelete,
  onReindex,
  onProcess,
  onReplace,
  isProcessing,
  isReplacing,
  onClick,
}: DocumentCardProps) {
  const replaceInputRef = useRef<HTMLInputElement>(null);
  const reduceMotion = useReducedMotion();
  const fileConfig = getFileConfig(doc.file_type);
  const FileIcon = fileConfig.icon;
  const sizeStr = doc.file_size >= 1024 * 1024
    ? `${(doc.file_size / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.round(doc.file_size / 1024)} KB`;

  const isActive = doc.status === "parsing" || doc.status === "indexing" || doc.status === "processing";

  // 处理中已用时间
  const [elapsed, setElapsed] = useState("");
  useEffect(() => {
    if (!isActive) { setElapsed(""); return; }
    const start = new Date(doc.updated_at).getTime();
    const tick = () => {
      const sec = Math.floor((Date.now() - start) / 1000);
      if (sec < 60) setElapsed(`${sec}s`);
      else setElapsed(`${Math.floor(sec / 60)}m ${sec % 60}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [isActive, doc.updated_at]);

  // 用户刚点击“分析”时的闪烁动画
  const [justTriggered, setJustTriggered] = useState(false);
  useEffect(() => {
    if (justTriggered) {
      const t = setTimeout(() => setJustTriggered(false), 1200);
      return () => clearTimeout(t);
    }
  }, [justTriggered]);

  const handleProcess = (e: React.MouseEvent) => {
    e.stopPropagation();
    setJustTriggered(true);
    onProcess(doc.id);
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
      animate={{
        opacity: 1,
        y: 0,
        ...(justTriggered && !reduceMotion ? { scale: [1, 0.98, 1] } : {}),
      }}
      exit={{ opacity: 0, y: reduceMotion ? 0 : -8 }}
      transition={
        reduceMotion
          ? MOTION_INSTANT
          : justTriggered
            ? { duration: 0.26, ease: EASE_OUT }
            : SPRING_CONTROL
      }
      className={cn(
        "ui-clickable-card group relative rounded-xl border bg-card",
        // 处理中的激活状态 —— 边框发光动画
        isActive
          ? "border-blue-400/50 shadow-[0_0_12px_-3px_rgba(96,165,250,0.3)]"
          : "border-border",
        selected && "border-primary ring-1 ring-primary/30 shadow-sm",
        doc.status === "indexed" ? "cursor-pointer" : "cursor-default",
        justTriggered && "ring-2 ring-blue-400/60",
      )}
      role={doc.status === "indexed" ? "button" : undefined}
      tabIndex={doc.status === "indexed" ? 0 : undefined}
      aria-pressed={doc.status === "indexed" ? !!selected : undefined}
      onClick={() => onClick?.(doc)}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget || doc.status !== "indexed") return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.(doc);
        }
      }}
    >
      {/* 处理中的微光遮罩层 */}
      {isActive && (
        <div className="absolute inset-0 rounded-lg overflow-hidden pointer-events-none">
          <div className="absolute inset-0 -translate-x-full animate-[shimmer_2s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-blue-400/[0.07] to-transparent" />
        </div>
      )}

      <div className="relative flex items-start gap-2.5 px-3 py-3">
        {/* 文件图标 */}
        <div className={cn(
          "mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl transition-colors",
          isActive ? "bg-blue-400/10" : "bg-muted/50",
        )}>
          {isActive ? (
            <Loader2 className="h-4.5 w-4.5 animate-spin text-blue-400" />
          ) : (
            <FileIcon className={cn("h-4.5 w-4.5", fileConfig.color)} />
          )}
        </div>

        {/* 内容 */}
        <div className="flex-1 min-w-0">
          <p className="truncate pr-1 text-[13px] font-medium" title={doc.original_filename}>
            {doc.original_filename}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <StatusBadge status={doc.status} />
            <span className="whitespace-nowrap text-[10px] text-muted-foreground">{sizeStr}</span>
            {doc.parser_version && (
              <span className="truncate text-[10px] text-muted-foreground/60">{doc.parser_version}</span>
            )}
            {isActive && (
              <span className="text-[10px] text-blue-400/80 font-medium animate-pulse">
                分析中{elapsed ? `（${elapsed}）` : "..."}
              </span>
            )}
          </div>
          <MetadataChips doc={doc} />
          {doc.error_message && (
            <p className="text-xs text-destructive mt-1 truncate">{doc.error_message}</p>
          )}
        </div>

        {/* 操作 */}
        <div className={cn(
          "absolute right-2 top-2 flex items-center gap-0.5 rounded-lg border bg-card/95 p-0.5 shadow-md transition-opacity",
          doc.status === "pending" || doc.status === "failed"
            ? "opacity-100"
            : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
        )}>
          <input
            ref={replaceInputRef}
            type="file"
            accept=".pdf,.txt,.md,.docx,.pptx"
            className="hidden"
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => {
              const nextFile = event.target.files?.[0];
              if (nextFile) onReplace(doc.id, nextFile);
              // 清空一下，不然连续选择同一个文件，浏览器会装没看见。
              event.target.value = "";
            }}
          />
          {/* 分析按钮 —— 待处理/失败的文档可见 */}
          {(doc.status === "pending" || doc.status === "failed") && (
            <Button
              variant="default"
              size="sm"
              onClick={handleProcess}
              disabled={isProcessing}
              className="h-7 text-xs gap-1.5"
            >
              {isProcessing ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Sparkles className="w-3 h-3" />
              )}
              分析
            </Button>
          )}
          {/* 已索引文档的重新处理 —— 仅悬停时显示 */}
          {doc.status === "indexed" && (
            <>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation();
                  replaceInputRef.current?.click();
                }}
                disabled={isReplacing}
                className="h-7 w-7"
                title="替换文件并增量更新"
              >
                {isReplacing
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <FileUp className="w-3.5 h-3.5" />}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => { e.stopPropagation(); onReindex(doc.id); }}
                className="h-7 w-7"
                title="强制重新分析"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </Button>
            </>
          )}
          {/* 删除 —— 仅悬停时显示 */}
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onDelete(doc.id); }}
            className="h-7 w-7"
            title={`删除 ${doc.original_filename}`}
            aria-label={`删除 ${doc.original_filename}`}
          >
            <Trash2 className="w-3.5 h-3.5 text-destructive" />
          </Button>
        </div>
      </div>
    </motion.div>
  );
});
