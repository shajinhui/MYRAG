import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useWorkspaces, useCreateWorkspace, useDeleteWorkspace } from "@/hooks/useWorkspaces";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Plus,
  Database,
  FileText,
  Trash2,
  MoreHorizontal,
  X,
} from "lucide-react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { FADE_REDUCED, SPRING_PANEL } from "@/lib/motion";
import type { KnowledgeBase } from "@/types";

export function KnowledgeBasesPage() {
  const reduceMotion = useReducedMotion();
  const navigate = useNavigate();
  const { data: workspaces, isLoading } = useWorkspaces();
  const createWorkspace = useCreateWorkspace();
  const deleteWorkspace = useDeleteWorkspace();
  const [showNewWorkspace, setShowNewWorkspace] = useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [openMenu, setOpenMenu] = useState<number | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const createTriggerRef = useRef<HTMLElement | null>(null);

  const openNewWorkspace = useCallback(() => {
    createTriggerRef.current = document.activeElement as HTMLElement | null;
    setShowNewWorkspace(true);
  }, []);

  const closeNewWorkspace = useCallback(() => {
    setShowNewWorkspace(false);
    window.requestAnimationFrame(() => createTriggerRef.current?.focus());
  }, []);

  // 点击外部时关闭菜单
  useEffect(() => {
    if (openMenu === null) return;
    const close = () => setOpenMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [openMenu]);

  useEffect(() => {
    if (!showNewWorkspace) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeNewWorkspace();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [showNewWorkspace, closeNewWorkspace]);

  const handleCreateWorkspace = async () => {
    if (!newWorkspaceName.trim()) return;
    try {
      const ws = await createWorkspace.mutateAsync({ name: newWorkspaceName });
      toast.success("知识库已创建");
      setNewWorkspaceName("");
      closeNewWorkspace();
      navigate(`/knowledge-bases/${ws.id}`);
    } catch {
      toast.error("创建知识库失败");
    }
  };

  const handleDeleteWorkspace = async (id: number) => {
    try {
      await deleteWorkspace.mutateAsync(id);
      toast.success("知识库已删除");
    } catch {
      toast.error("删除知识库失败");
    }
    setDeleteConfirm(null);
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    if (days === 0) return "今天";
    if (days === 1) return "昨天";
    if (days < 7) return `${days} 天前`;
    return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        {/* 区块标题 + 操作 */}
        <div className="mb-8 flex items-end justify-between gap-6">
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-primary">Workspace</p>
            <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.035em]">知识库</h1>
            <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
              整理文档、构建索引，并在同一个空间里完成检索、问答与内容核对。
              {workspaces && workspaces.length > 0 ? ` 当前共 ${workspaces.length} 个。` : ""}
            </p>
          </div>
          <Button onClick={openNewWorkspace} size="sm">
            <Plus className="w-4 h-4 mr-1.5" />
            新建知识库
          </Button>
        </div>

        {/* 新建工作区弹窗 */}
        {createPortal(
          <AnimatePresence>
          {showNewWorkspace && (
          <motion.div
            className="app-dialog-backdrop fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={FADE_REDUCED}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) closeNewWorkspace();
            }}
          >
            <motion.div
              ref={dialogRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="new-workspace-title"
              initial={{ opacity: 0, y: reduceMotion ? 0 : 12, scale: reduceMotion ? 1 : 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: reduceMotion ? 0 : 8, scale: reduceMotion ? 1 : 0.985 }}
              transition={reduceMotion ? FADE_REDUCED : SPRING_PANEL}
              className="mx-4 w-full max-w-md"
            >
            <Card className="shadow-2xl">
              <CardContent className="pt-6">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 id="new-workspace-title" className="text-lg font-semibold">新建知识库</h2>
                    <p className="mt-0.5 text-xs text-muted-foreground">先命名，文档可以稍后添加。</p>
                  </div>
                  <button
                    type="button"
                    onClick={closeNewWorkspace}
                    className="app-icon-button w-8 h-8"
                    aria-label="关闭新建知识库对话框"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <Input
                  placeholder="知识库名称"
                  value={newWorkspaceName}
                  onChange={(e) => setNewWorkspaceName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateWorkspace()}
                  autoFocus
                />
                <div className="flex justify-end gap-2 mt-4">
                  <Button variant="ghost" onClick={closeNewWorkspace}>
                    取消
                  </Button>
                  <Button onClick={handleCreateWorkspace} disabled={createWorkspace.isPending || !newWorkspaceName.trim()}>
                    {createWorkspace.isPending ? "创建中..." : "创建"}
                  </Button>
                </div>
              </CardContent>
            </Card>
            </motion.div>
          </motion.div>
          )}
          </AnimatePresence>,
          document.body,
        )}

        {/* 加载骨架屏 */}
        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="正在加载知识库">
            {[1, 2, 3].map((i) => (
              <Card key={i} className="animate-pulse">
                <CardContent className="pt-5 pb-4">
                  <div className="h-5 bg-muted rounded w-3/4 mb-3" />
                  <div className="h-3 bg-muted rounded w-1/2" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : !workspaces || workspaces.length === 0 ? (
          <div className="ui-card flex flex-col items-center justify-center rounded-2xl border border-dashed bg-card/40 px-6 py-20">
            <div className="workspace-empty-icon mb-5 h-16 w-16">
              <Database className="w-8 h-8" />
            </div>
            <h3 className="text-xl font-semibold mb-2">创建你的第一个知识库</h3>
            <p className="text-muted-foreground text-center max-w-sm mb-6">
              知识库用于存储你的文档，并支持跨文档的 AI 检索。
              你可以把它们作为数据源链接到任意项目。
            </p>
            <Button onClick={openNewWorkspace} size="lg">
              <Plus className="w-4 h-4 mr-2" />
              新建知识库
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {workspaces.map((ws: KnowledgeBase) => (
              <Card
                key={ws.id}
                role="button"
                tabIndex={0}
                aria-label={`打开知识库 ${ws.name}`}
                className="ui-clickable-card group cursor-pointer"
                onClick={() => navigate(`/knowledge-bases/${ws.id}`)}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate(`/knowledge-bases/${ws.id}`);
                  }
                }}
              >
                <CardContent className="flex min-h-[154px] flex-col pb-4 pt-5">
                  <div className="flex items-start justify-between mb-1">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-primary/10">
                        <Database className="w-4 h-4 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <h2 className="truncate text-[15px] font-semibold">{ws.name}</h2>
                        {ws.description && (
                          <p className="text-xs text-muted-foreground truncate mt-0.5">
                            {ws.description}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="relative flex-shrink-0">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenMenu(openMenu === ws.id ? null : ws.id);
                        }}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-[color,background-color,opacity] group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 hover:bg-muted"
                        aria-label={`更多操作：${ws.name}`}
                        title={`更多操作：${ws.name}`}
                      >
                        <MoreHorizontal className="w-4 h-4" />
                      </button>
                      {openMenu === ws.id && (
                        <div className="absolute right-0 top-8 z-20 bg-card border rounded-lg shadow-lg py-1 w-32">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteConfirm(ws.id);
                              setOpenMenu(null);
                            }}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-destructive hover:bg-muted transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            删除
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-5 text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <FileText className="w-3 h-3" />
                      {ws.document_count} 个文档
                    </span>
                    <span className="flex items-center gap-1 text-green-500">
                      {ws.indexed_count} 已索引
                    </span>
                    {ws.updated_at && (
                      <>
                        <span className="text-border">|</span>
                        <span>{formatDate(ws.updated_at)}</span>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* 删除确认 */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onConfirm={() => deleteConfirm !== null && handleDeleteWorkspace(deleteConfirm)}
        onCancel={() => setDeleteConfirm(null)}
        title="删除知识库"
        message="确定要删除吗？该知识库中的所有文档、索引数据和知识图谱数据都将被永久删除。"
        confirmLabel="删除"
        variant="danger"
      />
    </div>
  );
}
