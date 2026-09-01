import { useState, useRef, useCallback, memo, useEffect } from "react";
import { Search, Loader2, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { RAGQueryMode, Document } from "@/types";

// ---------------------------------------------------------------------------
// 模式选择器
// ---------------------------------------------------------------------------
const MODES: { value: RAGQueryMode; label: string; description: string }[] = [
  { value: "hybrid", label: "混合", description: "结合知识图谱与向量检索" },
  { value: "vector_only", label: "向量", description: "仅进行语义相似度检索" },
  { value: "local", label: "本地知识图谱", description: "面向实体的图谱遍历" },
  { value: "global", label: "全局知识图谱", description: "高层主题提取" },
];

// ---------------------------------------------------------------------------
// SearchBar 组件
// ---------------------------------------------------------------------------
interface SearchBarProps {
  onSearch: (query: string, mode: RAGQueryMode, topK: number, documentIds?: number[]) => void;
  isSearching?: boolean;
  documents?: Document[];
}

export const SearchBar = memo(function SearchBar({ onSearch, isSearching, documents }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<RAGQueryMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [showFilters, setShowFilters] = useState(false);
  const [selectedDocs, setSelectedDocs] = useState<number[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // 键盘快捷键：按 `/` 聚焦搜索框
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleSubmit = useCallback(() => {
    if (!query.trim() || isSearching) return;
    onSearch(query.trim(), mode, topK, selectedDocs.length > 0 ? selectedDocs : undefined);
  }, [query, mode, topK, selectedDocs, isSearching, onSearch]);

  const toggleDoc = useCallback((id: number) => {
    setSelectedDocs((prev) => prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]);
  }, []);

  const indexedDocs = documents?.filter((d) => d.status === "indexed") ?? [];

  return (
    <div className="space-y-3">
      {/* 主搜索行 */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          <input
            ref={inputRef}
            type="text"
            placeholder="输入与文档相关的问题..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            className={cn(
              "w-full h-10 pl-9 pr-16 rounded-lg border border-input bg-background text-sm",
              "placeholder:text-muted-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              "transition-shadow"
            )}
          />
          {/* 快捷键提示 */}
          {!query && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground/50 font-mono pointer-events-none">
              /
            </span>
          )}
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
        <Button
          onClick={handleSubmit}
          disabled={!query.trim() || isSearching}
          className="h-10 px-4"
        >
          {isSearching ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Search className="w-4 h-4" />
          )}
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={() => setShowFilters(!showFilters)}
          className={cn("h-10 w-10", showFilters && "bg-primary/10 border-primary/30")}
          title="搜索选项"
        >
          <Sparkles className="w-4 h-4" />
        </Button>
      </div>

      {/* 可展开的筛选器 */}
      {showFilters && (
        <div className="rounded-lg border bg-card/50 p-3 space-y-3">
          {/* 模式选择器 */}
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">搜索模式</label>
            <div className="flex gap-1.5 flex-wrap">
              {MODES.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setMode(m.value)}
                  title={m.description}
                  className={cn(
                    "px-2.5 py-1 text-xs font-medium rounded-md transition-colors",
                    mode === m.value
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground"
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {/* 结果数量 */}
          <div className="flex items-center gap-3">
            <label className="text-xs font-medium text-muted-foreground whitespace-nowrap">结果数量</label>
            <input
              type="range"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="flex-1 h-1.5 accent-primary"
            />
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Math.min(20, Math.max(1, Number(e.target.value))))}
              className="w-12 h-7 text-center text-xs rounded-md border border-input bg-background"
            />
          </div>

          {/* 文档范围 */}
          {indexedDocs.length > 1 && (
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                搜索范围{selectedDocs.length > 0 ? `（已选 ${selectedDocs.length} 个）` : "（全部文档）"}
              </label>
              <div className="flex gap-1.5 flex-wrap max-h-20 overflow-y-auto">
                {indexedDocs.map((d) => (
                  <button
                    key={d.id}
                    onClick={() => toggleDoc(d.id)}
                    className={cn(
                      "px-2 py-0.5 text-xs rounded-md transition-colors truncate max-w-[200px]",
                      selectedDocs.includes(d.id)
                        ? "bg-primary/15 text-primary border border-primary/30"
                        : "bg-muted text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {d.original_filename}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
});
