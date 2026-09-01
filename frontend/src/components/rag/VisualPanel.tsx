import { memo } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  BookOpen,
  Network,
  List,
  FileSearch,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { FADE_ENTER, MOTION_INSTANT } from "@/lib/motion";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { DocumentViewer } from "./DocumentViewer";
import { KnowledgeGraphView } from "./KnowledgeGraphView";
import { AnalyticsDashboard } from "./AnalyticsDashboard";
import { EntityList } from "./EntityList";

// ---------------------------------------------------------------------------
// 标签按钮
// ---------------------------------------------------------------------------
function TabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "ui-button flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors",
        active
          ? "bg-card text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground hover:bg-muted"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// 子标签按钮（更小，用于知识图谱内部标签）
// ---------------------------------------------------------------------------
function SubTabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded transition-colors",
        active
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// 空状态
// ---------------------------------------------------------------------------
function EmptyVisual() {
  return (
    <section className="workspace-panel h-full min-w-0" aria-label="文档预览">
      <header className="workspace-panel-header">
        <div className="flex min-w-0 items-center gap-2">
          <FileSearch className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">预览</span>
        </div>
      </header>
      <div className="workspace-empty-state flex-1 px-4">
      <div className="workspace-empty-icon mb-3">
        <FileSearch className="w-6 h-6" />
      </div>
        <p className="text-sm font-medium text-foreground/80">选择一篇文档</p>
        <p className="mt-1 max-w-[220px] text-center text-[11px] leading-relaxed text-muted-foreground">
          在左侧选择已索引的文档，内容与引用会在这里保持同步。
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// KG 内容 —— 图谱 + 分析拆分，或完整实体列表
// ---------------------------------------------------------------------------
const KGContent = memo(function KGContent({
  workspaceId,
  highlightEntities,
}: {
  workspaceId: string;
  highlightEntities: string[];
}) {
  const { kgSubTab, setKgSubTab } = useWorkspaceStore();

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* 子标签栏 */}
      <div className="flex-shrink-0 flex items-center gap-1 px-3 py-1.5 border-b bg-muted/20">
        <SubTabButton
          active={kgSubTab === "graph"}
          icon={<Network className="w-3 h-3" />}
          label="图谱"
          onClick={() => setKgSubTab("graph")}
        />
        <SubTabButton
          active={kgSubTab === "entities"}
          icon={<List className="w-3 h-3" />}
          label="实体"
          onClick={() => setKgSubTab("entities")}
        />
      </div>

      {/* 内容 */}
      {kgSubTab === "graph" ? (
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          {/* 图谱 —— 60% */}
          <div className="flex-[6] min-h-0 overflow-hidden border-b">
            <KnowledgeGraphView
              projectId={workspaceId}
              highlightEntities={highlightEntities}
            />
          </div>
          {/* 分析 —— 40% */}
          <div className="flex-[4] min-h-0 overflow-y-auto p-3">
            <AnalyticsDashboard projectId={workspaceId} compact />
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <EntityList
            projectId={workspaceId}
            highlightEntities={highlightEntities}
          />
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// VisualPanel —— 主导出
// ---------------------------------------------------------------------------
interface VisualPanelProps {
  workspaceId: string;
  hasMyragDocs: boolean;
}

export const VisualPanel = memo(function VisualPanel({
  workspaceId,
  hasMyragDocs,
}: VisualPanelProps) {
  const reduceMotion = useReducedMotion();
  const {
    selectedDoc,
    activeTab,
    setActiveTab,
    scrollToPage,
    scrollToHeading,
    scrollToImageSrc,
    highlightChunks,
    highlightEntities,
    clearScrollTarget,
  } = useWorkspaceStore();

  if (!selectedDoc) return <EmptyVisual />;

  return (
    <section className="workspace-panel h-full min-w-0 overflow-hidden" aria-label="文档预览">
      {/* 标签栏 */}
      <header className="workspace-panel-header gap-2 px-3">
        <div className="mr-auto flex min-w-0 items-center gap-2">
          <FileSearch className="h-4 w-4 flex-shrink-0 text-primary" />
          <span className="truncate text-sm font-semibold">预览</span>
        </div>
        <div className="flex flex-shrink-0 items-center gap-0.5 rounded-xl bg-muted/40 p-0.5" role="tablist" aria-label="预览方式">
        <TabButton
          active={activeTab === "content"}
          icon={<BookOpen className="w-3.5 h-3.5" />}
          label="内容"
          onClick={() => setActiveTab("content")}
        />
        {hasMyragDocs && (
          <TabButton
            active={activeTab === "kg"}
            icon={<Network className="w-3.5 h-3.5" />}
            label="知识图谱"
            onClick={() => setActiveTab("kg")}
          />
        )}
        </div>
        {/* 激活高亮指示器 */}
        {highlightChunks.length > 0 && (
          <span className="hidden rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary 2xl:inline-flex">
            {highlightChunks.length} 处高亮
          </span>
        )}
      </header>

      {/* 内容区域 */}
      <div className="relative flex-1 min-h-0 overflow-hidden">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: reduceMotion ? 0 : activeTab === "kg" ? 8 : -8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: reduceMotion ? 0 : activeTab === "kg" ? -8 : 8 }}
            transition={reduceMotion ? MOTION_INSTANT : FADE_ENTER}
            className="h-full"
          >
            {activeTab === "content" ? (
              <DocumentViewer
                doc={selectedDoc}
                scrollToPage={scrollToPage}
                scrollToHeading={scrollToHeading}
                scrollToImageSrc={scrollToImageSrc}
                highlightChunks={highlightChunks}
                onScrolled={clearScrollTarget}
              />
            ) : (
              <KGContent
                workspaceId={workspaceId}
                highlightEntities={highlightEntities}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  );
});
