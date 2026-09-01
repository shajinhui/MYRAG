import { useState, useMemo, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  Users,
  Building2,
  MapPin,
  Lightbulb,
  Calendar,
  Tag,
  Loader2,
  Network,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { entityTypeLabel } from "@/lib/entityLabels";
import { api } from "@/lib/api";
import type { KGEntity, KGRelationship } from "@/types";

// ---------------------------------------------------------------------------
// 实体类型配置 —— 图标 + 颜色
// ---------------------------------------------------------------------------
const ENTITY_TYPE_CONFIG: Record<string, { icon: typeof Tag; color: string; bg: string }> = {
  person:       { icon: Users,     color: "text-blue-400",   bg: "bg-blue-400/15" },
  organization: { icon: Building2, color: "text-primary",    bg: "bg-primary/15" },
  location:     { icon: MapPin,    color: "text-amber-400",  bg: "bg-amber-400/15" },
  event:        { icon: Calendar,  color: "text-orange-400", bg: "bg-orange-400/15" },
  concept:      { icon: Lightbulb, color: "text-purple-400", bg: "bg-purple-400/15" },
};

function getEntityConfig(type: string) {
  const key = type.toLowerCase();
  return ENTITY_TYPE_CONFIG[key] ?? { icon: Tag, color: "text-muted-foreground", bg: "bg-muted" };
}

// ---------------------------------------------------------------------------
// TypeBadge 组件
// ---------------------------------------------------------------------------
function TypeBadge({ type }: { type: string }) {
  const config = getEntityConfig(type);
  const Icon = config.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full", config.bg, config.color)}>
      <Icon className="w-3 h-3" />
      {entityTypeLabel(type)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// RelationshipRow —— 实体展开时显示
// ---------------------------------------------------------------------------
function RelationshipRow({ rel, entityName }: { rel: KGRelationship; entityName: string }) {
  const isSource = rel.source.toLowerCase() === entityName.toLowerCase();
  const other = isSource ? rel.target : rel.source;

  return (
    <div className="flex items-center gap-2 text-xs py-1.5 px-3">
      <span className={cn("font-medium truncate max-w-[140px]", isSource ? "text-foreground" : "text-muted-foreground")}>
        {isSource ? entityName : other}
      </span>
      <ArrowRight className="w-3 h-3 text-muted-foreground/50 flex-shrink-0" />
      <span className="text-muted-foreground/70 truncate max-w-[160px] italic">
        {rel.description || rel.keywords || "相关"}
      </span>
      <ArrowRight className="w-3 h-3 text-muted-foreground/50 flex-shrink-0" />
      <span className={cn("font-medium truncate max-w-[140px]", isSource ? "text-muted-foreground" : "text-foreground")}>
        {isSource ? other : entityName}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EntityRow —— 实体表格中的单行
// ---------------------------------------------------------------------------
const EntityRow = memo(function EntityRow({
  entity,
  projectId,
}: {
  entity: KGEntity;
  projectId: string;
}) {
  const [expanded, setExpanded] = useState(false);

  // 仅在展开时懒加载关系
  const { data: relationships, isLoading: relsLoading } = useQuery({
    queryKey: ["kg-relationships", projectId, entity.name],
    queryFn: () => api.get<KGRelationship[]>(`/rag/relationships/${projectId}?entity=${encodeURIComponent(entity.name)}&limit=20`),
    enabled: expanded,
    staleTime: 60_000,
  });

  return (
    <div className="border-b last:border-b-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted/50 transition-colors text-left"
        data-entity-name={entity.name}
      >
        {/* 名称 */}
        <span className="font-medium text-sm truncate flex-1 min-w-0">{entity.name}</span>

        {/* 类型徽章 */}
        <TypeBadge type={entity.entity_type} />

        {/* 关联度 */}
        <span className="text-xs text-muted-foreground/60 w-8 text-right flex-shrink-0">
          {entity.degree}
        </span>

        {/* 展开 */}
        {entity.degree > 0 && (
          expanded
            ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
            : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        )}
      </button>

      {/* 展开区域：描述 + 关系 */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-2">
              {/* 描述 */}
              {entity.description && (
                <p className="text-xs text-muted-foreground/80 leading-relaxed pl-1">
                  {entity.description}
                </p>
              )}

              {/* 关系 */}
              {relsLoading && (
                <div className="flex items-center gap-2 py-2 px-1">
                  <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">正在加载关系...</span>
                </div>
              )}
              {relationships && relationships.length > 0 && (
                <div className="rounded-md bg-muted/30 border divide-y">
                  {relationships.map((rel, i) => (
                    <RelationshipRow key={i} rel={rel} entityName={entity.name} />
                  ))}
                </div>
              )}
              {relationships && relationships.length === 0 && (
                <p className="text-xs text-muted-foreground/50 pl-1">未找到关系</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

// ---------------------------------------------------------------------------
// 排序选项
// ---------------------------------------------------------------------------
type SortKey = "degree" | "name" | "type";

// ---------------------------------------------------------------------------
// EntityList 组件
// ---------------------------------------------------------------------------
interface EntityListProps {
  projectId: string;
  highlightEntities?: string[];
}

export const EntityList = memo(function EntityList({ projectId, highlightEntities = [] }: EntityListProps) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>("degree");

  const { data: entities, isLoading } = useQuery({
    queryKey: ["kg-entities", projectId],
    queryFn: () => api.get<KGEntity[]>(`/rag/entities/${projectId}?limit=500`),
    staleTime: 30_000,
  });

  // 用于筛选的唯一实体类型
  const entityTypes = useMemo(() => {
    if (!entities) return [];
    const types = new Set(entities.map((e) => e.entity_type));
    return Array.from(types).sort();
  }, [entities]);

  // 筛选 + 排序
  const filtered = useMemo(() => {
    if (!entities) return [];
    let result = entities;

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((e) => e.name.toLowerCase().includes(q) || e.description.toLowerCase().includes(q));
    }

    if (typeFilter) {
      result = result.filter((e) => e.entity_type.toLowerCase() === typeFilter.toLowerCase());
    }

    if (sortBy === "name") {
      result = [...result].sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "type") {
      result = [...result].sort((a, b) => a.entity_type.localeCompare(b.entity_type) || b.degree - a.degree);
    }
    // 默认“关联度”排序已由 API 提供

    return result;
  }, [entities, search, typeFilter, sortBy]);

  if (isLoading) {
    return (
      <div className="space-y-2 animate-pulse">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-10 rounded-md bg-muted" />
        ))}
      </div>
    );
  }

  if (!entities || entities.length === 0) {
    return (
      <div className="flex flex-col items-center py-10 text-center">
        <Network className="w-10 h-10 text-muted-foreground/30 mb-3" />
        <p className="text-sm text-muted-foreground">尚未提取到实体</p>
        <p className="text-xs text-muted-foreground/60 mt-1">
          使用 MYRAG 处理文档时会自动提取实体
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 控件：搜索 + 筛选 */}
      <div className="flex gap-2 flex-wrap">
        {/* 搜索 */}
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            placeholder="搜索实体..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-8 pl-8 pr-3 rounded-md border border-input bg-background text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>

        {/* 类型筛选 */}
        <select
          value={typeFilter ?? ""}
          onChange={(e) => setTypeFilter(e.target.value || null)}
          className="h-8 px-2 rounded-md border border-input bg-background text-xs"
        >
          <option value="">全部类型</option>
          {entityTypes.map((t) => (
            <option key={t} value={t}>{entityTypeLabel(t)}</option>
          ))}
        </select>

        {/* 排序 */}
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          className="h-8 px-2 rounded-md border border-input bg-background text-xs"
        >
          <option value="degree">关联度最高</option>
          <option value="name">名称 A-Z</option>
          <option value="type">按类型</option>
        </select>
      </div>

      {/* 数量 + 类型标签 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground">
          {filtered.length} 个实体
        </span>
        {typeFilter && (
          <button
            onClick={() => setTypeFilter(null)}
            className="text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded-full hover:bg-primary/20 transition-colors"
          >
            {typeFilter} &times;
          </button>
        )}
      </div>

      {/* 表头 */}
      <div className="flex items-center gap-3 px-3 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider border-b">
        <span className="flex-1">实体</span>
        <span className="w-24">类型</span>
        <span className="w-8 text-right">关联</span>
        <span className="w-4" />
      </div>

      {/* 实体行 */}
      <div className="rounded-lg border divide-y max-h-[500px] overflow-y-auto">
        {filtered.map((entity, index) => {
          const isHighlighted = highlightEntities.some(
            (e) => e.toLowerCase() === entity.name.toLowerCase()
          );
          return (
            <div
              key={`${entity.name}-${entity.entity_type}-${index}`}
              className={cn(
                isHighlighted && "bg-amber-400/10 border-l-2 border-l-amber-400"
              )}
            >
              <EntityRow entity={entity} projectId={projectId} />
            </div>
          );
        })}
      </div>

      {filtered.length === 0 && entities.length > 0 && (
        <p className="text-center text-xs text-muted-foreground py-4">
          没有符合筛选条件的实体
        </p>
      )}
    </div>
  );
});
