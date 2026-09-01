import { useState, useMemo, useCallback, memo } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  FileText,
  Pencil,
  Check,
  X,
  Loader2,
  Sparkles,
  Settings2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UploadZone } from "./UploadZone";
import { StatsBar } from "./StatsBar";
import { DocumentFilters, type FilterStatus } from "./DocumentFilters";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { WorkspaceSettings } from "./WorkspaceSettings";
import { CustomMetadataInput } from "./CustomMetadataInput";
import { DocumentCard } from "./DocumentCard";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Document, RAGStats, DocumentStatus, KnowledgeBase, UpdateWorkspace } from "@/types";

const PROCESSING_STATUSES = new Set<DocumentStatus>([
  "parsing",
  "indexing",
  "processing",
]);
const PROCESSABLE_STATUSES = new Set<DocumentStatus>(["pending", "failed"]);

interface DataPanelProps {
  workspace: KnowledgeBase | undefined;
  documents: Document[] | undefined;
  docsLoading: boolean;
  ragStats: RAGStats | undefined;
  selectedDocId: number | null;
  onSelectDoc: (doc: Document) => void;
  onUpload: (file: File, customMetadata?: {key: string, value: string}[]) => void;
  isUploading: boolean;
  onDelete: (id: number) => void;
  onProcess: (id: number) => void;
  onReindex: (id: number) => void;
  onReplace: (id: number, file: File) => void;
  isProcessing: boolean;
  isReplacing: boolean;
  onUpdateWorkspace: (data: UpdateWorkspace) => Promise<void>;
}

export const DataPanel = memo(function DataPanel({
  workspace,
  documents,
  docsLoading,
  ragStats,
  selectedDocId,
  onSelectDoc,
  onUpload,
  isUploading,
  onDelete,
  onProcess,
  onReindex,
  onReplace,
  isProcessing,
  isReplacing,
  onUpdateWorkspace,
}: DataPanelProps) {
  const navigate = useNavigate();
  const [deleteDocConfirm, setDeleteDocConfirm] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [isEditingName, setIsEditingName] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [batchProcessing, setBatchProcessing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [customMetadata, setCustomMetadata] = useState<{key: string, value: string}[]>([]);

  const handleUpload = useCallback((file: File) => {
    const validMeta = customMetadata.filter((m) => m.key.trim() !== "");
    onUpload(file, validMeta.length > 0 ? validMeta : undefined);
    // 可选：上传成功后是否清空元数据？保留以便连续上传多个文件。
  }, [customMetadata, onUpload]);

  const processingCount = useMemo(
    () => documents?.filter((d) => PROCESSING_STATUSES.has(d.status)).length ?? 0,
    [documents]
  );

  const pendingCount = useMemo(
    () => documents?.filter((d) => PROCESSABLE_STATUSES.has(d.status)).length ?? 0,
    [documents]
  );

  const filteredDocs = useMemo(() => {
    if (!documents) return [];
    let result = documents;
    if (statusFilter !== "all") {
      if (statusFilter === "parsing") {
        result = result.filter((d) => PROCESSING_STATUSES.has(d.status));
      } else {
        result = result.filter((d) => d.status === statusFilter);
      }
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((d) =>
        d.original_filename.toLowerCase().includes(q)
      );
    }
    return result;
  }, [documents, statusFilter, searchQuery]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: 0 };
    documents?.forEach((d) => {
      counts.all = (counts.all || 0) + 1;
      counts[d.status] = (counts[d.status] || 0) + 1;
    });
    return counts as Record<FilterStatus, number>;
  }, [documents]);

  const handleBatchProcess = useCallback(async () => {
    if (!documents || batchProcessing) return;
    const processable = documents.filter((d) => PROCESSABLE_STATUSES.has(d.status));
    if (processable.length === 0) return;

    setBatchProcessing(true);
    const count = processable.length;
    toast.info(`正在分析 ${count} 个文档...`, {
      description: "文档将按顺序处理。",
    });

    try {
      await api.post("/rag/process-batch", {
        document_ids: processable.map((d) => d.id),
      });
    } catch {
      toast.error("批量分析启动失败");
    } finally {
      setBatchProcessing(false);
    }
  }, [documents, batchProcessing]);

  const handleStartEdit = () => {
    if (workspace) {
      setEditName(workspace.name);
      setEditDesc(workspace.description || "");
      setIsEditingName(true);
    }
  };

  const handleSaveEdit = async () => {
    if (!editName.trim()) return;
    await onUpdateWorkspace({
      name: editName.trim(),
      description: editDesc.trim() || undefined,
    });
    setIsEditingName(false);
  };

  return (
    <section className="workspace-panel workspace-panel--data h-full min-w-0 overflow-hidden" aria-label="数据与文档">
      {/* 头部 —— 工作区名称 */}
      <header className="workspace-panel-header block h-auto min-h-[72px] px-3 py-2.5">
        <button
          type="button"
          onClick={() => navigate("/")}
          className="app-nav-item -ml-1 mb-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-muted-foreground"
        >
          <ArrowLeft className="w-3 h-3" />
          控制台
        </button>

        {isEditingName ? (
          <div className="space-y-1.5" aria-label="编辑知识库信息">
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSaveEdit()}
              placeholder="名称"
              autoFocus
              className="text-sm font-semibold h-8"
            />
            <Input
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
              placeholder="描述"
              className="text-xs h-7"
            />
            <div className="flex items-center gap-1">
              <Button size="sm" onClick={handleSaveEdit} disabled={!editName.trim()} className="h-6 text-[10px] px-2">
                <Check className="w-3 h-3 mr-0.5" /> 保存
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setIsEditingName(false)} className="h-6 text-[10px] px-2">
                <X className="w-3 h-3 mr-0.5" /> 取消
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <div className="flex-1 min-w-0">
              <h1 className="truncate text-[15px] font-semibold">
                {workspace?.name || "知识库"}
              </h1>
              {workspace?.description && (
                <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                  {workspace.description}
                </p>
              )}
            </div>
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setSettingsOpen(true)}
              className="h-6 w-6 flex-shrink-0"
              title="工作区设置"
              aria-label="工作区设置"
            >
              <Settings2 className="w-3 h-3" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              onClick={handleStartEdit}
              className="h-6 w-6 flex-shrink-0"
              title="编辑名称与描述"
              aria-label="编辑名称与描述"
            >
              <Pencil className="w-3 h-3" />
            </Button>
          </div>
        )}
      </header>

      {/* 上传区域头部与设置 */}
      <div className="flex flex-shrink-0 items-center justify-between px-3 pb-1 pt-2.5">
        <h3 className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted-foreground">
          添加文档
        </h3>
        <CustomMetadataInput metadata={customMetadata} onChange={setCustomMetadata} />
      </div>

      {/* 上传区域 —— 始终可见，约占 15% */}
      <div className="h-[112px] flex-shrink-0 px-3 pb-2">
        <UploadZone onUpload={handleUpload} isUploading={isUploading} mini />
      </div>

      {/* 统计栏 */}
      <div className="flex-shrink-0 space-y-2 border-b px-3 pb-2.5 pt-1">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-1.5 text-xs font-semibold">
            <FileText className="w-3.5 h-3.5" />
            文档
          </h2>
          <span className="text-[10px] text-muted-foreground">
            {documents?.length ?? 0} 个文件
          </span>
        </div>
        <StatsBar stats={ragStats} processingCount={processingCount} />

        {/* “全部分析”横幅 —— 为窄面板做紧凑设计 */}
        {pendingCount > 0 && (
          <button
            onClick={handleBatchProcess}
            disabled={batchProcessing || processingCount > 0}
            className={cn(
              "ui-button w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-xl",
              "border border-blue-400/20 bg-blue-400/[0.06]",
              "hover:bg-blue-400/10 transition-colors",
              (batchProcessing || processingCount > 0) && "opacity-50 pointer-events-none",
            )}
          >
            <div className="flex items-center gap-2 min-w-0">
              <Sparkles className={cn("w-3.5 h-3.5 text-blue-400 flex-shrink-0", batchProcessing && "animate-spin")} />
              <span className="text-[11px] font-medium text-blue-400 truncate">
                {batchProcessing ? "启动中..." : `全部分析（${pendingCount}）`}
              </span>
            </div>
            <span className="text-[10px] text-muted-foreground flex-shrink-0">
              {pendingCount} 个待处理
            </span>
          </button>
        )}
      </div>

      {/* 文档列表 —— 约占 80% */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {docsLoading ? (
          <div className="workspace-empty-state" role="status">
            <Loader2 className="w-4 h-4 animate-spin text-muted-foreground mr-2" />
            <span className="text-xs text-muted-foreground">正在加载文档...</span>
          </div>
        ) : !documents || documents.length === 0 ? (
          <div className="workspace-empty-state px-5">
            <div className="workspace-empty-icon">
              <FileText className="h-5 w-5" />
            </div>
            <p className="text-xs font-medium text-foreground/80">还没有文档</p>
            <p className="mt-1 max-w-[220px] text-center text-[10px] leading-relaxed text-muted-foreground">
              将 PDF、Word 或 Markdown 文件拖到上方，上传后即可分析和提问。
            </p>
          </div>
        ) : (
          <>
            <div className="flex-shrink-0 px-3 pt-2.5">
              <DocumentFilters
                searchQuery={searchQuery}
                onSearchChange={setSearchQuery}
                statusFilter={statusFilter}
                onStatusChange={setStatusFilter}
                counts={statusCounts}
              />
            </div>

            <div className="flex-1 space-y-1.5 overflow-y-auto px-3 py-2.5">
              <AnimatePresence mode="popLayout">
                {filteredDocs.map((doc) => (
                  <DocumentCard
                    key={doc.id}
                    doc={doc}
                    selected={doc.id === selectedDocId}
                    onDelete={setDeleteDocConfirm}
                    onReindex={onReindex}
                    onProcess={onProcess}
                    onReplace={onReplace}
                    isProcessing={isProcessing}
                    isReplacing={isReplacing}
                    onClick={onSelectDoc}
                  />
                ))}
              </AnimatePresence>
              {filteredDocs.length === 0 && documents.length > 0 && (
                <div className="rounded-xl border border-dashed px-3 py-5 text-center text-[11px] text-muted-foreground">
                  没有符合当前筛选的文档
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* 工作区设置遮罩层 */}
      {workspace && (
        <WorkspaceSettings
          workspace={workspace}
          onSave={onUpdateWorkspace}
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {/* 删除确认 */}
      <ConfirmDialog
        open={deleteDocConfirm !== null}
        onConfirm={async () => {
          if (deleteDocConfirm !== null) {
            onDelete(deleteDocConfirm);
            setDeleteDocConfirm(null);
          }
        }}
        onCancel={() => setDeleteDocConfirm(null)}
        title="删除文档"
        message="确定要删除吗？此操作会删除该文档及其索引数据。"
        confirmLabel="删除"
        variant="danger"
      />
    </section>
  );
});
