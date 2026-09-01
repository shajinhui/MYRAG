import {
  useMemo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Bot,
  Database,
  FileSearch,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  type LucideIcon,
} from "lucide-react";
import { DataPanel } from "@/components/rag/DataPanel";
import { ChatPanel } from "@/components/rag/ChatPanel";
import { VisualPanel } from "@/components/rag/VisualPanel";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useWorkspace, useUpdateWorkspace } from "@/hooks/useWorkspaces";
import { api } from "@/lib/api";
import { FADE_FAST, MOTION_INSTANT, SPRING_PANEL } from "@/lib/motion";
import type {
  Document,
  DocumentReplaceResponse,
  RAGStats,
  DocumentStatus,
  UpdateWorkspace,
} from "@/types";

const PROCESSING_STATUSES = new Set<DocumentStatus>([
  "parsing",
  "indexing",
  "processing",
]);

type WorkspacePanelKey = "data" | "chat" | "visual";
type CollapsedPanels = Record<WorkspacePanelKey, boolean>;
type PanelRatios = Record<WorkspacePanelKey, number>;

interface ResizeDragState {
  pointerId: number;
  leftPanel: WorkspacePanelKey;
  rightPanel: WorkspacePanelKey;
  startX: number;
  startLeftWidth: number;
  startRightWidth: number;
  combinedRatio: number;
}

const PANEL_STORAGE_KEY = "myrag-workspace-collapsed-panels";
const PANEL_SIZE_STORAGE_KEY = "myrag-workspace-panel-ratios";
const PANEL_COLLAPSED_WIDTH = 46;
const PANEL_KEYBOARD_STEP = 24;
const DEFAULT_COLLAPSED_PANELS: CollapsedPanels = {
  data: false,
  chat: false,
  visual: false,
};
const DEFAULT_PANEL_RATIOS: PanelRatios = {
  data: 0.78,
  chat: 1.4,
  visual: 1,
};
const PANEL_MIN_WIDTH: Record<WorkspacePanelKey, number> = {
  data: 180,
  chat: 260,
  visual: 200,
};

function loadCollapsedPanels(): CollapsedPanels {
  try {
    const stored = localStorage.getItem(PANEL_STORAGE_KEY);
    if (!stored) return DEFAULT_COLLAPSED_PANELS;
    const parsed = JSON.parse(stored) as Partial<CollapsedPanels>;
    return {
      data: parsed.data === true,
      chat: parsed.chat === true,
      visual: parsed.visual === true,
    };
  } catch {
    return DEFAULT_COLLAPSED_PANELS;
  }
}

function loadPanelRatios(): PanelRatios {
  try {
    const stored = localStorage.getItem(PANEL_SIZE_STORAGE_KEY);
    if (!stored) return DEFAULT_PANEL_RATIOS;
    const parsed = JSON.parse(stored) as Partial<PanelRatios>;
    const isValid = (value: unknown): value is number =>
      typeof value === "number" && Number.isFinite(value) && value > 0;
    if (!isValid(parsed.data) || !isValid(parsed.chat) || !isValid(parsed.visual)) {
      return DEFAULT_PANEL_RATIOS;
    }
    return { data: parsed.data, chat: parsed.chat, visual: parsed.visual };
  } catch {
    return DEFAULT_PANEL_RATIOS;
  }
}

function resizePanelPair(
  current: PanelRatios,
  drag: Omit<ResizeDragState, "pointerId" | "startX">,
  delta: number,
): PanelRatios {
  const pairWidth = drag.startLeftWidth + drag.startRightWidth;
  if (pairWidth <= 0) return current;

  const nominalMinLeft = PANEL_MIN_WIDTH[drag.leftPanel];
  const nominalMinRight = PANEL_MIN_WIDTH[drag.rightPanel];
  const minScale = Math.min(1, pairWidth / (nominalMinLeft + nominalMinRight));
  const minLeft = nominalMinLeft * minScale;
  const minRight = nominalMinRight * minScale;
  const nextLeftWidth = Math.min(
    pairWidth - minRight,
    Math.max(minLeft, drag.startLeftWidth + delta),
  );
  const leftShare = nextLeftWidth / pairWidth;

  return {
    ...current,
    [drag.leftPanel]: drag.combinedRatio * leftShare,
    [drag.rightPanel]: drag.combinedRatio * (1 - leftShare),
  };
}

function WorkspacePanelSlot({
  panel,
  label,
  icon: Icon,
  collapsed,
  grow,
  isResizing,
  onToggle,
  children,
}: {
  panel: WorkspacePanelKey;
  label: string;
  icon: LucideIcon;
  collapsed: boolean;
  grow: number;
  isResizing: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const reduceMotion = useReducedMotion();
  const isRightPanel = panel === "visual";
  const CollapseIcon = isRightPanel ? PanelRightClose : PanelLeftClose;
  const ExpandIcon = isRightPanel ? PanelRightOpen : PanelLeftOpen;
  const contentId = `workspace-panel-${panel}`;

  return (
    <motion.div
      className="workspace-panel-slot"
      data-panel={panel}
      data-collapsed={collapsed || undefined}
      layout={!isResizing}
      style={{
        flexBasis: collapsed ? PANEL_COLLAPSED_WIDTH : 0,
        flexGrow: collapsed ? 0 : grow,
        flexShrink: collapsed ? 0 : 1,
        minWidth: collapsed ? PANEL_COLLAPSED_WIDTH : 0,
      }}
      transition={reduceMotion ? MOTION_INSTANT : SPRING_PANEL}
    >
      <motion.div
        id={contentId}
        className="workspace-panel-content h-full min-w-0"
        aria-hidden={collapsed || undefined}
        inert={collapsed || undefined}
        initial={false}
        animate={{ opacity: collapsed ? 0 : 1 }}
        transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
      >
        {children}
      </motion.div>

      <AnimatePresence initial={false}>
        {collapsed ? (
          <motion.button
            key="rail"
            type="button"
            className="workspace-panel-rail ui-button"
            onClick={onToggle}
            aria-label={`展开${label}`}
            aria-controls={contentId}
            aria-expanded={false}
            title={`展开${label}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
          >
            <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
            <span className="workspace-panel-rail-label">{label}</span>
            <ExpandIcon className="mt-auto h-4 w-4" aria-hidden="true" />
          </motion.button>
        ) : (
          <motion.button
            key="collapse"
            type="button"
            className="workspace-panel-collapse app-icon-button ui-button"
            onClick={onToggle}
            aria-label={`收起${label}`}
            aria-controls={contentId}
            aria-expanded={true}
            title={`收起${label}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
          >
            <CollapseIcon className="h-3.5 w-3.5" aria-hidden="true" />
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function WorkspaceResizeHandle({
  leftPanel,
  rightPanel,
  leftLabel,
  rightLabel,
  ratios,
  active,
  onPointerDown,
  onKeyboardResize,
  onReset,
}: {
  leftPanel: WorkspacePanelKey;
  rightPanel: WorkspacePanelKey;
  leftLabel: string;
  rightLabel: string;
  ratios: PanelRatios;
  active: boolean;
  onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onKeyboardResize: (delta: number) => void;
  onReset: () => void;
}) {
  const pairTotal = ratios[leftPanel] + ratios[rightPanel];
  const leftPercent = Math.round((ratios[leftPanel] / pairTotal) * 100);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      onKeyboardResize(-PANEL_KEYBOARD_STEP);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      onKeyboardResize(PANEL_KEYBOARD_STEP);
    } else if (event.key === "Home") {
      event.preventDefault();
      onReset();
    }
  };

  return (
    <div
      className="workspace-resize-handle"
      data-active={active || undefined}
      role="separator"
      tabIndex={0}
      aria-label={`调整${leftLabel}和${rightLabel}宽度`}
      aria-orientation="vertical"
      aria-valuemin={10}
      aria-valuemax={90}
      aria-valuenow={leftPercent}
      title="拖动调整宽度 · 左右方向键微调 · 双击恢复默认"
      onPointerDown={onPointerDown}
      onKeyDown={handleKeyDown}
      onDoubleClick={onReset}
    >
      <span className="workspace-resize-grip" aria-hidden="true" />
    </div>
  );
}

export function WorkspacePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const wsId = workspaceId ? Number(workspaceId) : null;
  const gridRef = useRef<HTMLDivElement>(null);
  const resizeDragRef = useRef<ResizeDragState | null>(null);
  const [collapsedPanels, setCollapsedPanels] = useState<CollapsedPanels>(loadCollapsedPanels);
  const [panelRatios, setPanelRatios] = useState<PanelRatios>(loadPanelRatios);
  const [resizingPair, setResizingPair] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(collapsedPanels));
  }, [collapsedPanels]);

  useEffect(() => {
    if (!resizingPair) {
      localStorage.setItem(PANEL_SIZE_STORAGE_KEY, JSON.stringify(panelRatios));
    }
  }, [panelRatios, resizingPair]);

  const togglePanel = useCallback((panel: WorkspacePanelKey) => {
    setCollapsedPanels((current) => ({
      ...current,
      [panel]: !current[panel],
    }));
  }, []);

  const beginResize = useCallback((
    leftPanel: WorkspacePanelKey,
    rightPanel: WorkspacePanelKey,
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    if (event.button !== 0) return;
    const grid = gridRef.current;
    const leftElement = grid?.querySelector<HTMLElement>(`[data-panel="${leftPanel}"]`);
    const rightElement = grid?.querySelector<HTMLElement>(`[data-panel="${rightPanel}"]`);
    if (!leftElement || !rightElement) return;

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeDragRef.current = {
      pointerId: event.pointerId,
      leftPanel,
      rightPanel,
      startX: event.clientX,
      startLeftWidth: leftElement.getBoundingClientRect().width,
      startRightWidth: rightElement.getBoundingClientRect().width,
      combinedRatio: panelRatios[leftPanel] + panelRatios[rightPanel],
    };
    setResizingPair(`${leftPanel}-${rightPanel}`);
  }, [panelRatios]);

  const updateResize = useCallback((pointerId: number, clientX: number) => {
    const drag = resizeDragRef.current;
    if (!drag || drag.pointerId !== pointerId) return;
    const delta = clientX - drag.startX;
    setPanelRatios((current) => resizePanelPair(current, drag, delta));
  }, []);

  const finishResize = useCallback((pointerId?: number) => {
    const drag = resizeDragRef.current;
    if (!drag || (pointerId !== undefined && drag.pointerId !== pointerId)) return;
    resizeDragRef.current = null;
    setResizingPair(null);
  }, []);

  useEffect(() => {
    if (!resizingPair) return;

    const handlePointerMove = (event: PointerEvent) => {
      event.preventDefault();
      updateResize(event.pointerId, event.clientX);
    };
    const handlePointerEnd = (event: PointerEvent) => finishResize(event.pointerId);
    const handleWindowBlur = () => finishResize();

    window.addEventListener("pointermove", handlePointerMove, { passive: false });
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);
    window.addEventListener("blur", handleWindowBlur);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
      window.removeEventListener("blur", handleWindowBlur);
    };
  }, [finishResize, resizingPair, updateResize]);

  const resizeWithKeyboard = useCallback((
    leftPanel: WorkspacePanelKey,
    rightPanel: WorkspacePanelKey,
    delta: number,
  ) => {
    const grid = gridRef.current;
    const leftElement = grid?.querySelector<HTMLElement>(`[data-panel="${leftPanel}"]`);
    const rightElement = grid?.querySelector<HTMLElement>(`[data-panel="${rightPanel}"]`);
    if (!leftElement || !rightElement) return;
    const startLeftWidth = leftElement.getBoundingClientRect().width;
    const startRightWidth = rightElement.getBoundingClientRect().width;
    setPanelRatios((current) => resizePanelPair(current, {
      leftPanel,
      rightPanel,
      startLeftWidth,
      startRightWidth,
      combinedRatio: current[leftPanel] + current[rightPanel],
    }, delta));
  }, []);

  const resetPanelPair = useCallback((
    leftPanel: WorkspacePanelKey,
    rightPanel: WorkspacePanelKey,
  ) => {
    setPanelRatios((current) => {
      const combinedRatio = current[leftPanel] + current[rightPanel];
      const defaultCombined = DEFAULT_PANEL_RATIOS[leftPanel] + DEFAULT_PANEL_RATIOS[rightPanel];
      const leftShare = DEFAULT_PANEL_RATIOS[leftPanel] / defaultCombined;
      return {
        ...current,
        [leftPanel]: combinedRatio * leftShare,
        [rightPanel]: combinedRatio * (1 - leftShare),
      };
    });
  }, []);

  // -- 工作区数据 --
  const { data: workspace } = useWorkspace(wsId);
  const updateWorkspace = useUpdateWorkspace();

  // -- 状态存储 --
  const { selectedDoc, selectDoc, reset: resetStore } = useWorkspaceStore();

  // 切换工作区时重置 Store
  useEffect(() => {
    resetStore();
  }, [workspaceId, resetStore]);

  // -----------------------------------------------------------------------
  // 查询
  // -----------------------------------------------------------------------
  const { data: documents, isLoading: docsLoading } = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () =>
      api.get<Document[]>(`/documents/workspace/${workspaceId}`),
    enabled: !!workspaceId,
    refetchInterval: (query) => {
      const docs = query.state.data;
      if (docs?.some((d) => PROCESSING_STATUSES.has(d.status))) return 3000;
      return false;
    },
  });

  const { data: ragStats } = useQuery({
    queryKey: ["rag-stats", workspaceId],
    queryFn: () => api.get<RAGStats>(`/rag/stats/${workspaceId}`),
    enabled: !!workspaceId,
  });

  // -----------------------------------------------------------------------
  // 处理完成时刷新 ragStats
  // -----------------------------------------------------------------------
  const processingCount = useMemo(
    () =>
      documents?.filter((d) => PROCESSING_STATUSES.has(d.status)).length ?? 0,
    [documents]
  );

  const prevProcessingRef = useRef(processingCount);
  useEffect(() => {
    if (prevProcessingRef.current > 0 && processingCount === 0) {
      queryClient.invalidateQueries({ queryKey: ["rag-stats", workspaceId] });
    }
    prevProcessingRef.current = processingCount;
  }, [processingCount, queryClient, workspaceId]);

  // 让 selectedDoc 与最新文档数据保持同步
  useEffect(() => {
    if (selectedDoc && documents) {
      const updated = documents.find((d) => d.id === selectedDoc.id);
      if (updated && updated.status !== selectedDoc.status) {
        selectDoc(updated);
      }
    }
  }, [documents, selectedDoc, selectDoc]);

  const hasIndexedDocs = (ragStats?.indexed_documents ?? 0) > 0;
  const hasMyragDocs = (ragStats?.myrag_documents ?? 0) > 0;

  // -----------------------------------------------------------------------
  // 变更操作
  // -----------------------------------------------------------------------
  const uploadDoc = useMutation({
    mutationFn: ({ file, customMetadata }: { file: File, customMetadata?: {key: string, value: string}[] }) =>
      api.uploadFile<Document>(`/documents/upload/${workspaceId}`, file, customMetadata),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["rag-stats", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("文档上传成功");
    },
    onError: () => toast.error("上传文档失败"),
  });

  const deleteDoc = useMutation({
    mutationFn: (docId: number) => api.delete(`/documents/${docId}`),
    onSuccess: (_, docId) => {
      queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["rag-stats", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      if (selectedDoc?.id === docId) selectDoc(null);
      toast.success("文档已删除");
    },
    onError: () => toast.error("删除文档失败"),
  });

  const processDoc = useMutation({
    mutationFn: (docId: number) => api.post(`/rag/process/${docId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["rag-stats", workspaceId] });
      toast.info("正在分析文档...", {
        description: "正在解析内容并构建搜索索引。",
      });
    },
    onError: (error: Error) => {
      if (error.message?.includes("already being analyzed")) {
        toast.info("文档正在分析中", {
          description: "请等待当前分析完成。",
        });
        // 刷新以获取最新状态
        queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
      } else {
        toast.error("分析启动失败");
      }
    },
  });

  const reindexDoc = useMutation({
    mutationFn: (docId: number) => api.post(`/rag/reindex/${docId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["rag-stats", workspaceId] });
      toast.success("已开始重新处理文档");
    },
    onError: () => toast.error("重新处理文档失败"),
  });

  const replaceDoc = useMutation({
    mutationFn: ({ docId, file }: { docId: number; file: File }) =>
      api.uploadFile<DocumentReplaceResponse>(
        `/documents/${docId}/file`,
        file,
        undefined,
        "PUT",
      ),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["rag-stats", workspaceId] });
      if (result.changed) {
        toast.info("文件已替换，正在增量更新", {
          description: "只处理这一篇，其他文档不用陪跑。",
        });
      } else {
        toast.success("文件没有变化，已跳过重复处理");
      }
    },
    onError: (error: Error) => toast.error(error.message || "替换文件失败"),
  });

  // -----------------------------------------------------------------------
  // 处理函数
  // -----------------------------------------------------------------------
  const handleSelectDoc = useCallback(
    (doc: Document) => {
      if (doc.status !== "indexed") return;
      if (selectedDoc?.id === doc.id) {
        selectDoc(null);
      } else {
        selectDoc(doc);
      }
    },
    [selectedDoc, selectDoc]
  );

  const handleUpdateWorkspace = useCallback(
    async (data: UpdateWorkspace) => {
      if (!wsId) return;
      await updateWorkspace.mutateAsync({ id: wsId, data });
    },
    [wsId, updateWorkspace]
  );

  // -----------------------------------------------------------------------
  // 渲染 —— 三栏布局
  // -----------------------------------------------------------------------
  return (
    <div
      ref={gridRef}
      className="workspace-grid h-full overflow-hidden"
      data-resizing={resizingPair ? true : undefined}
    >
      {/* 第 1 栏：数据区 */}
      <WorkspacePanelSlot
        panel="data"
        label="文档区"
        icon={Database}
        collapsed={collapsedPanels.data}
        grow={panelRatios.data}
        isResizing={!!resizingPair}
        onToggle={() => togglePanel("data")}
      >
        <DataPanel
          workspace={workspace}
          documents={documents}
          docsLoading={docsLoading}
          ragStats={ragStats}
          selectedDocId={selectedDoc?.id ?? null}
          onSelectDoc={handleSelectDoc}
          onUpload={(file, customMetadata) => uploadDoc.mutate({ file, customMetadata })}
          isUploading={uploadDoc.isPending}
          onDelete={(id) => deleteDoc.mutate(id)}
          onProcess={(id) => processDoc.mutate(id)}
          onReindex={(id) => reindexDoc.mutate(id)}
          onReplace={(id, file) => replaceDoc.mutate({ docId: id, file })}
          isProcessing={processDoc.isPending}
          isReplacing={replaceDoc.isPending}
          onUpdateWorkspace={handleUpdateWorkspace}
        />
      </WorkspacePanelSlot>

      {!collapsedPanels.data && !collapsedPanels.chat && (
        <WorkspaceResizeHandle
          leftPanel="data"
          rightPanel="chat"
          leftLabel="文档区"
          rightLabel="AI 助手"
          ratios={panelRatios}
          active={resizingPair === "data-chat"}
          onPointerDown={(event) => beginResize("data", "chat", event)}
          onKeyboardResize={(delta) => resizeWithKeyboard("data", "chat", delta)}
          onReset={() => resetPanelPair("data", "chat")}
        />
      )}

      {/* 第 2 栏：聊天区 */}
      <WorkspacePanelSlot
        panel="chat"
        label="AI 助手"
        icon={Bot}
        collapsed={collapsedPanels.chat}
        grow={panelRatios.chat}
        isResizing={!!resizingPair}
        onToggle={() => togglePanel("chat")}
      >
        <ChatPanel
          workspaceId={workspaceId || ""}
          hasIndexedDocs={hasIndexedDocs}
          workspace={workspace ?? null}
        />
      </WorkspacePanelSlot>

      {!collapsedPanels.chat && !collapsedPanels.visual && (
        <WorkspaceResizeHandle
          leftPanel="chat"
          rightPanel="visual"
          leftLabel="AI 助手"
          rightLabel="预览区"
          ratios={panelRatios}
          active={resizingPair === "chat-visual"}
          onPointerDown={(event) => beginResize("chat", "visual", event)}
          onKeyboardResize={(delta) => resizeWithKeyboard("chat", "visual", delta)}
          onReset={() => resetPanelPair("chat", "visual")}
        />
      )}

      {/* 第 3 栏：可视化区 */}
      <WorkspacePanelSlot
        panel="visual"
        label="预览区"
        icon={FileSearch}
        collapsed={collapsedPanels.visual}
        grow={panelRatios.visual}
        isResizing={!!resizingPair}
        onToggle={() => togglePanel("visual")}
      >
        <VisualPanel
          workspaceId={workspaceId || ""}
          hasMyragDocs={hasMyragDocs}
        />
      </WorkspacePanelSlot>
    </div>
  );
}
