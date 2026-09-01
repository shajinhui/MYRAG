import { useState, useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";
import {
  Settings2,
  X,
  Save,
  RotateCcw,
  Plus,
  Globe,
  Tags,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { entityTypeLabel } from "@/lib/entityLabels";
import type { KnowledgeBase, UpdateWorkspace } from "@/types";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

const LANGUAGE_OPTIONS = [
  { value: "", label: "默认（使用服务器设置）" },
  { value: "English", label: "英语" },
  { value: "Vietnamese", label: "越南语" },
  { value: "Chinese", label: "中文" },
  { value: "Japanese", label: "日语" },
  { value: "Korean", label: "韩语" },
  { value: "French", label: "法语" },
  { value: "German", label: "德语" },
  { value: "Spanish", label: "西班牙语" },
];

const DEFAULT_ENTITY_TYPES = [
  "Organization", "Person", "Product", "Location", "Event",
  "Financial_Metric", "Technology", "Date", "Regulation",
];

// ---------------------------------------------------------------------------
// 组件属性
// ---------------------------------------------------------------------------

interface WorkspaceSettingsProps {
  workspace: KnowledgeBase;
  onSave: (data: UpdateWorkspace) => Promise<void>;
  open: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// 标签输入（用于实体类型）
// ---------------------------------------------------------------------------

function TagInput({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const addTag = (value: string) => {
    const trimmed = value.trim().replace(/\s+/g, "_");
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInput("");
  };

  const removeTag = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    } else if (e.key === "Backspace" && !input && tags.length > 0) {
      removeTag(tags.length - 1);
    }
  };

  return (
    <div
      className="flex flex-wrap gap-1.5 p-2 min-h-[40px] rounded-md border border-input bg-background cursor-text"
      onClick={() => inputRef.current?.focus()}
    >
      {tags.map((tag, i) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-md bg-primary/10 text-primary border border-primary/20"
        >
          {entityTypeLabel(tag)}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); removeTag(i); }}
            className="hover:text-destructive transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => { if (input.trim()) addTag(input); }}
        placeholder={tags.length === 0 ? placeholder : "添加类型..."}
        className="flex-1 min-w-[80px] bg-transparent text-xs outline-none placeholder:text-muted-foreground"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export function WorkspaceSettings({
  workspace,
  onSave,
  open,
  onClose,
}: WorkspaceSettingsProps) {
  const [language, setLanguage] = useState(workspace.kg_language ?? "");
  const [entityTypes, setEntityTypes] = useState<string[]>(
    workspace.kg_entity_types ?? []
  );
  const [saving, setSaving] = useState(false);

  // 工作区变化时同步
  useEffect(() => {
    setLanguage(workspace.kg_language ?? "");
    setEntityTypes(workspace.kg_entity_types ?? []);
  }, [workspace.kg_language, workspace.kg_entity_types]);

  const hasChanges =
    language !== (workspace.kg_language ?? "") ||
    JSON.stringify(entityTypes) !== JSON.stringify(workspace.kg_entity_types ?? []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await onSave({
        kg_language: language || null,
        kg_entity_types: entityTypes.length > 0 ? entityTypes : null,
      });
      toast.success("工作区设置已保存");
      onClose();
    } catch {
      toast.error("保存设置失败");
    } finally {
      setSaving(false);
    }
  }, [language, entityTypes, onSave, onClose]);

  const handleReset = () => {
    setLanguage("");
    setEntityTypes([]);
  };

  const handleLoadDefaults = () => {
    setEntityTypes(DEFAULT_ENTITY_TYPES);
  };

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-50 bg-background/95 backdrop-blur-sm flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 border-b flex-shrink-0">
        <div className="flex items-center gap-2">
          <Settings2 className="w-4 h-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">工作区设置</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} className="h-7 w-7">
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {/* KG 语言 */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Globe className="w-3.5 h-3.5" />
            知识图谱语言
          </label>
          <Select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="h-8 text-xs"
          >
            {LANGUAGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </Select>
          <p className="text-[10px] text-muted-foreground">
            用于知识图谱实体提取的语言。留空表示使用服务器默认值。
          </p>
        </div>

        {/* KG 实体类型 */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Tags className="w-3.5 h-3.5" />
              知识图谱实体类型
            </label>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLoadDefaults}
              className="h-6 text-[10px] px-2 text-muted-foreground"
            >
              <Plus className="w-3 h-3 mr-0.5" />
              加载默认值
            </Button>
          </div>
          <TagInput
            tags={entityTypes}
            onChange={setEntityTypes}
            placeholder="组织、人物、产品..."
          />
          <p className="text-[10px] text-muted-foreground">
            知识图谱提取使用的实体类型。按 Enter 或逗号添加。留空表示使用服务器默认值。
          </p>
        </div>

        {/* 信息框 */}
        <div className="rounded-md border border-blue-400/20 bg-blue-400/5 p-2.5">
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            这些设置会影响此工作区中文档的处理方式。
            修改只对重新分析后的文档生效，已有文档会保留当前知识图谱数据。
            如需应用新设置，请重新分析文档。
          </p>
        </div>
      </div>

      {/* 底部 */}
      <div className="flex items-center justify-between px-3 py-2 border-t flex-shrink-0">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleReset}
          className="h-7 text-xs gap-1"
        >
          <RotateCcw className="w-3 h-3" />
          重置为默认值
        </Button>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-7 text-xs">
            取消
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className="h-7 text-xs gap-1"
          >
            <Save className="w-3 h-3" />
            {saving ? "保存中..." : "保存"}
          </Button>
        </div>
      </div>
    </div>
  );
}
