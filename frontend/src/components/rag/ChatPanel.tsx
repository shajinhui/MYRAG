import { useState, useRef, useEffect, useCallback, useMemo, memo, createContext, useContext, Children, isValidElement, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  Send,
  Square,
  Bot,
  User,
  Loader2,
  Trash2,
  Sparkles,
  FileText,
  Save,
  ImageIcon,
  Brain,
  ChevronDown,
  Settings,
  RotateCcw,
  Info,
  Copy,
  ClipboardCheck,
  FileCode,
  ThumbsUp,
  ThumbsDown,
  DatabaseZap,
} from "lucide-react";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp";
import diff from "react-syntax-highlighter/dist/esm/languages/prism/diff";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import { toast } from "sonner";
import { cn, generateId } from "@/lib/utils";
import { FADE_REDUCED, MOTION_INSTANT, SPRING_PANEL } from "@/lib/motion";
import { api } from "@/lib/api";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useThemeStore } from "@/stores/useThemeStore";

SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("js", javascript);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("ts", typescript);
SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("sh", bash);
SyntaxHighlighter.registerLanguage("shell", bash);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("css", css);
SyntaxHighlighter.registerLanguage("html", markup);
SyntaxHighlighter.registerLanguage("xml", markup);
SyntaxHighlighter.registerLanguage("yaml", yaml);
SyntaxHighlighter.registerLanguage("yml", yaml);
SyntaxHighlighter.registerLanguage("java", java);
SyntaxHighlighter.registerLanguage("go", go);
SyntaxHighlighter.registerLanguage("cpp", cpp);
SyntaxHighlighter.registerLanguage("c", cpp);
SyntaxHighlighter.registerLanguage("diff", diff);
SyntaxHighlighter.registerLanguage("markdown", markdown);
SyntaxHighlighter.registerLanguage("md", markdown);
import { useUpdateWorkspace } from "@/hooks/useWorkspaces";
import { useChatHistory, useClearChatHistory } from "@/hooks/useChatHistory";
import { useRAGChatStream } from "@/hooks/useRAGChatStream";
import { StreamingMarkdown } from "@/components/rag/MemoizedMarkdown";
import { ThinkingTimeline } from "@/components/rag/ThinkingTimeline";
import type {
  ChatMessage,
  ChatImageRef,
  ChatSourceChunk,
  ChatStreamStatus,
  Document,
  KnowledgeBase,
  LLMCapabilities,
  AgentStep,
} from "@/types";

// 上下文，用于向嵌套组件提供 workspaceId 和 debugMode
const WsIdCtx = createContext<string>("");
const DebugCtx = createContext(false);

// 上下文：整个对话中所有消息的来源汇总。
// 当消息引用了之前轮次的引用 ID 时，用作回退。
const AllSourcesCtx = createContext<ChatSourceChunk[]>([]);

/** 通过 document_id 从 react-query 缓存中查找文档 */
function useFindDoc(documentId: number): Document | undefined {
  const wsId = useContext(WsIdCtx);
  const qc = useQueryClient();
  const docs = qc.getQueryData<Document[]>(["documents", wsId]);
  return docs?.find((d) => d.id === documentId);
}

// ---------------------------------------------------------------------------
// 辅助函数：缩短文件名，用于引用展示
// ---------------------------------------------------------------------------
function shortenDocName(filename: string, maxLen = 14): string {
  const name = filename.replace(/\.[^.]+$/, ""); // 去掉扩展名
  if (name.length <= maxLen) return name;
  return name.slice(0, maxLen - 1) + "\u2026"; // 省略号
}

// ---------------------------------------------------------------------------
// 引用徽章 —— 可点击的 [N] 标记 → 图标 + 文档名-P.N
// ---------------------------------------------------------------------------
function CitationLink({
  index,
  source,
  relatedEntities,
}: {
  index: string;
  source: ChatSourceChunk;
  relatedEntities: string[];
}) {
  const { activateCitation, activateCitationKG } =
    useWorkspaceStore();
  const doc = useFindDoc(source.document_id);

  const isKG = source.source_type === "kg";

  const handleContentClick = () => {
    if (isKG) {
      activateCitationKG(source, relatedEntities, doc);
    } else {
      activateCitation(source, relatedEntities, doc);
    }
  };

  const handleKGClick = () => {
    activateCitationKG(source, relatedEntities, doc);
  };

  if (isKG) {
    // 知识图谱来源 —— 带大脑图标的紫色标签
    return (
      <button
        onClick={handleContentClick}
        className="inline-flex items-center gap-0.5 h-[18px] px-1.5 mx-0.5 text-[10px] font-medium rounded-full bg-purple-400/15 text-purple-500 dark:text-purple-400 hover:bg-purple-400/25 transition-colors align-middle whitespace-nowrap"
        title="在知识图谱中查看"
      >
        <Brain className="w-2.5 h-2.5 flex-shrink-0" />
        <span>KG-{index}</span>
      </button>
    );
  }

  // 向量来源 —— 带文件图标的蓝色标签 + 文档名-P.N
  const docName = doc?.original_filename
    ? shortenDocName(doc.original_filename)
    : `来源 ${index}`;
  const label = `${docName}-P.${source.page_no || "?"}`;

  return (
    <span className="inline-flex gap-0.5 mx-0.5 align-middle">
      <button
        onClick={handleContentClick}
        className="inline-flex items-center gap-0.5 h-[18px] px-1.5 text-[10px] font-medium rounded-full bg-primary/12 text-primary hover:bg-primary/20 transition-colors whitespace-nowrap"
        title={`查看来源：${doc?.original_filename || "未知"}（第 ${source.page_no} 页）`}
      >
        <FileText className="w-2.5 h-2.5 flex-shrink-0" />
        <span>{label}</span>
      </button>
      <button
        onClick={handleKGClick}
        className="inline-flex items-center justify-center w-[18px] h-[18px] text-[10px] font-bold rounded-full bg-purple-400/15 text-purple-500 dark:text-purple-400 hover:bg-purple-400/25 transition-colors"
        title="在知识图谱中高亮"
      >
        <Brain className="w-2.5 h-2.5" />
      </button>
    </span>
  );
}

// ---------------------------------------------------------------------------
// 内联图片徽章 —— 可点击的 [IMG-N] → 图标 + 文档名-P.N，并带预览
// ---------------------------------------------------------------------------
function InlineImageRef({
  imgRefId,
  imageRef,
}: {
  imgRefId: string;
  imageRef: ChatImageRef;
}) {
  const [showPreview, setShowPreview] = useState(false);
  const { activateImageCitation } = useWorkspaceStore();
  const doc = useFindDoc(imageRef.document_id);

  const handleClick = () => {
    setShowPreview((p) => !p);
    activateImageCitation(imageRef, doc);
  };

  const docName = doc?.original_filename
    ? shortenDocName(doc.original_filename)
    : `图片 ${imgRefId}`;
  const label = `${docName}-P.${imageRef.page_no || "?"}`;

  return (
    <span className="inline-flex flex-col mx-0.5">
      <button
        onClick={handleClick}
        className="inline-flex items-center gap-0.5 h-[18px] px-1.5 text-[10px] font-medium rounded-full bg-emerald-400/15 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-400/25 transition-colors align-middle whitespace-nowrap"
        title={imageRef.caption || `来自第 ${imageRef.page_no} 页的图片`}
      >
        <ImageIcon className="w-2.5 h-2.5 flex-shrink-0" />
        <span>{label}</span>
      </button>
      {showPreview && (
        <a
          href={imageRef.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block mt-1 rounded-md overflow-hidden border bg-white max-w-[280px] hover:border-primary/50 transition-colors"
        >
          <img
            src={imageRef.url}
            alt={imageRef.caption || `来自第 ${imageRef.page_no} 页的图片`}
            className="w-full h-auto max-h-[180px] object-contain"
          />
          {imageRef.caption && (
            <span className="block px-2 py-1 text-[9px] text-muted-foreground leading-tight border-t bg-muted/30">
              p.{imageRef.page_no} — {imageRef.caption}
            </span>
          )}
        </a>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// 处理 React 子节点，将 [XXXX] 和 [IMG-XXXX] 替换为交互组件。
// 同时支持新的 [a3x9] 和旧的 [1] 引用格式。
// 也处理 [a3x9, b2m7] 这类成组括号，拆分后逐项处理。
// ---------------------------------------------------------------------------
const CITATION_RE = /(\[(?:[a-z0-9]+|IMG-[a-z0-9]+)(?:,\s*(?:[a-z0-9]+|IMG-[a-z0-9]+))*\])/g;

function injectCitations(
  children: ReactNode,
  sources: ChatSourceChunk[],
  relatedEntities: string[],
  imageRefs?: ChatImageRef[],
  fallbackSources?: ChatSourceChunk[],
): ReactNode {
  return Children.map(children, (child) => {
    // 处理字符串节点 —— 按引用模式拆分
    if (typeof child === "string") {
      const parts = child.split(CITATION_RE);
      if (parts.length === 1) return child;
      const result: ReactNode[] = [];
      parts.forEach((part, i) => {
        // 检查这部分是否为括号组
        const bracketMatch = part.match(/^\[(.+)\]$/);
        if (!bracketMatch) {
          if (part) result.push(part);
          return;
        }
        // 按逗号拆分成组引用 [a3x9, b2m7]
        const tokens = bracketMatch[1].split(/,\s*/);
        tokens.forEach((token, ti) => {
          const key = `${i}-${ti}`;
          // 图片引用：IMG-xxxx
          const imgMatch = token.match(/^IMG-(.+)$/);
          if (imgMatch && imageRefs && imageRefs.length > 0) {
            const imgId = imgMatch[1];
            // 优先按 ref_id 匹配，再回退到旧的数字索引
            const imageRef =
              imageRefs.find((ir) => ir.ref_id === imgId) ??
              imageRefs[parseInt(imgId, 10) - 1]; // 旧格式从 1 开始索引
            if (imageRef) {
              result.push(<InlineImageRef key={key} imgRefId={imgId} imageRef={imageRef} />);
              return;
            }
          }
          // 文本引用：按索引（字符串或数字）匹配来源
          // 先尝试当前消息的来源，再回退到历史来源
          const source =
            sources.find((s) => String(s.index) === token) ??
            (fallbackSources ? fallbackSources.find((s) => String(s.index) === token) : undefined);
          if (source) {
            result.push(
              <CitationLink key={key} index={String(source.index)} source={source} relatedEntities={relatedEntities} />
            );
            return;
          }
          // 未匹配 —— 按原样渲染
          result.push(`[${token}]`);
        });
      });
      return result;
    }
    // 递归处理有子节点的 React 元素
    if (isValidElement(child) && child.props && (child.props as { children?: ReactNode }).children) {
      const props = child.props as { children?: ReactNode };
      return Object.assign({}, child, {
        props: {
          ...child.props,
          children: injectCitations(props.children, sources, relatedEntities, imageRefs, fallbackSources),
        },
      });
    }
    return child;
  });
}

// ---------------------------------------------------------------------------
// 预处理 Markdown：修复常见的 LLM 输出问题
// ---------------------------------------------------------------------------
function preprocessMarkdown(text: string): string {
  const lines = text.split("\n");
  const result: string[] = [];
  let prevWasTable = false;
  let inCodeFence = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      inCodeFence = !inCodeFence;
    }

    const isTable = (trimmed.startsWith("|") && trimmed.endsWith("|")) ||
      /^\|[\s:|-]+\|$/.test(trimmed);

    // 从表格行切换到非表格内容时插入空行
    if (prevWasTable && !isTable && trimmed !== "") {
      result.push("");
    }

    // 将单行显示公式 $$content$$ 转换为多行格式
    if (
      !inCodeFence &&
      trimmed.startsWith("$$") &&
      trimmed.endsWith("$$") &&
      trimmed.length > 4 &&
      trimmed !== "$$"
    ) {
      const mathContent = trimmed.slice(2, -2);
      result.push("$$");
      result.push(mathContent);
      result.push("$$");
    } else {
      result.push(line);
    }

    prevWasTable = isTable;
  }

  return result.join("\n");
}

// ---------------------------------------------------------------------------
// 从 React 节点树中提取原始文本（用于代码块）
// ---------------------------------------------------------------------------
function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    return extractText(props.children);
  }
  return "";
}

// ---------------------------------------------------------------------------
// 带语法高亮和复制按钮的代码块
// ---------------------------------------------------------------------------
function CodeBlock({
  language,
  children,
}: {
  language: string;
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const theme = useThemeStore((s) => s.theme);
  const isDark = theme === "dark";
  const code = extractText(children).replace(/\n$/, "");

  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="group relative my-2">
      {language && (
        <span className="absolute top-2 right-2 text-[9px] uppercase text-muted-foreground/40 font-mono select-none z-10 pointer-events-none">
          {language}
        </span>
      )}
      <button
        onClick={handleCopy}
        className={cn(
          "absolute top-2 left-2 p-1 rounded-md text-muted-foreground/50 hover:text-muted-foreground transition-all opacity-0 group-hover:opacity-100 z-10",
          isDark ? "bg-white/5 hover:bg-white/10" : "bg-black/5 hover:bg-black/10"
        )}
        title="复制代码"
      >
        {copied ? (
          <ClipboardCheck className="w-3 h-3 text-emerald-500" />
        ) : (
          <Copy className="w-3 h-3" />
        )}
      </button>
      <SyntaxHighlighter
        language={language}
        style={isDark ? oneDark : oneLight}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: "8px",
          fontSize: "12px",
          padding: "10px 12px",
          ...(isDark
            ? {
                background: "oklch(0.18 0.015 155)",
                border: "1px solid oklch(0.30 0.025 155)",
              }
            : {
                background: "oklch(0.96 0.008 105)",
                border: "1px solid oklch(0.88 0.018 105)",
              }),
        }}
        codeTagProps={{ style: { fontFamily: '"IBM Plex Mono", "Fira Code", monospace' } }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 带内联引用链接、LaTeX 和代码块的 Markdown 渲染器
// ---------------------------------------------------------------------------
function MarkdownWithCitations({
  content,
  sources,
  relatedEntities,
  imageRefs,
}: {
  content: string;
  sources: ChatSourceChunk[];
  relatedEntities: string[];
  imageRefs?: ChatImageRef[];
}) {
  const processed = preprocessMarkdown(content);

  // 回退：使用对话中所有消息的来源汇总。
  // 当模型引用了之前回答中的引用 ID（例如未调用 search_documents）时，
  // 仍然可以将它们渲染为链接。
  const allSources = useContext(AllSourcesCtx);

  // 创建包装组件，将引用注入到渲染后的子节点中
  const withCitations = (Tag: string) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ({ children, ...props }: any) => {
      const injected = injectCitations(children, sources, relatedEntities, imageRefs, allSources);
      return <Tag {...props}>{injected}</Tag>;
    };
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        p: withCitations("p"),
        li: withCitations("li"),
        td: withCitations("td"),
        th: withCitations("th"),
        h1: withCitations("h1"),
        h2: withCitations("h2"),
        h3: withCitations("h3"),
        h4: withCitations("h4"),
        h5: withCitations("h5"),
        h6: withCitations("h6"),
        strong: withCitations("strong"),
        em: withCitations("em"),
        a: ({ href, children, ...props }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
            {injectCitations(children, sources, relatedEntities, imageRefs, allSources)}
          </a>
        ),
        // 代码块 —— 交给 CodeBlock 做语法高亮
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        code: ({ className, children, ...props }: any) => {
          const langMatch = /language-(\w+)/.exec(className || "");
          // 行内代码（没有语言类）
          if (!langMatch) {
            return <code className={className} {...props}>{children}</code>;
          }
          // 围栏代码块 → 语法高亮
          return <CodeBlock language={langMatch[1]}>{children}</CodeBlock>;
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  );
}

// ---------------------------------------------------------------------------
// 来源评分按钮
// ---------------------------------------------------------------------------
type RelevanceRating = "relevant" | "partial" | "not_relevant";

function SourceRatingButtons({
  sourceIndex,
  currentRating,
  onRate,
}: {
  sourceIndex: string;
  currentRating?: RelevanceRating;
  onRate: (sourceIndex: string, rating: RelevanceRating) => void;
}) {
  return (
    <div
      className="flex items-center gap-1 flex-shrink-0"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRate(sourceIndex, "relevant");
        }}
        className={cn(
          "app-icon-button inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors",
          currentRating === "relevant"
            ? "text-emerald-500"
            : "text-muted-foreground/20 hover:text-emerald-500/60",
        )}
        aria-label={`标记来源 ${sourceIndex} 为相关`}
        title="相关"
      >
        <ThumbsUp className="h-3 w-3" />
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRate(sourceIndex, "not_relevant");
        }}
        className={cn(
          "app-icon-button inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors",
          currentRating === "not_relevant"
            ? "text-destructive"
            : "text-muted-foreground/20 hover:text-destructive/60",
        )}
        aria-label={`标记来源 ${sourceIndex} 为不相关`}
        title="不相关"
      >
        <ThumbsDown className="h-3 w-3" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 来源面板 —— 展示检索到的分块
// ---------------------------------------------------------------------------
function SourcesPanel({
  sources,
  messageId,
}: {
  sources: ChatSourceChunk[];
  messageId?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [ratings, setRatings] = useState<Record<string, RelevanceRating>>({});
  const { activateCitation, activateCitationKG } = useWorkspaceStore();
  const wsId = useContext(WsIdCtx);
  const debugMode = useContext(DebugCtx);

  if (sources.length === 0) return null;

  const vectorSources = sources.filter((s) => s.source_type !== "kg");
  const kgSources = sources.filter((s) => s.source_type === "kg");

  const handleRate = async (sourceIndex: string, rating: RelevanceRating) => {
    // 切换：再次点击相同评分取消评分
    const newRating = ratings[sourceIndex] === rating ? "partial" : rating;
    const prev = { ...ratings };
    setRatings((r) => ({ ...r, [sourceIndex]: newRating }));

    if (!messageId || !wsId) return;
    try {
      await api.post(`/rag/chat/${wsId}/rate`, {
        message_id: messageId,
        source_index: sourceIndex,
        rating: newRating,
      });
    } catch {
      setRatings(prev); // 回滚
    }
  };

  return (
    <div className="mt-2 rounded-md border bg-muted/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground transition-colors"
        aria-expanded={expanded}
      >
        <FileText className="w-3 h-3" />
        {vectorSources.length} 个来源
        {kgSources.length > 0 && " + 知识图谱"}
        <span className="ml-auto text-[10px]">{expanded ? "▲" : "▼"}</span>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="divide-y border-t">
              {vectorSources.map((source) => (
                <div
                  key={source.chunk_id}
                  className="relative hover:bg-muted/50 transition-colors"
                >
                  <button
                    type="button"
                    onClick={() => activateCitation(source, [])}
                    className={cn("w-full text-left px-2.5 py-2", messageId && "pr-[4.75rem]")}
                  >
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold rounded-full bg-primary/15 text-primary">
                        {source.index}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        p.{source.page_no}
                      </span>
                      {source.heading_path.length > 0 && (
                        <span className="text-[10px] text-muted-foreground/60 truncate">
                          {source.heading_path.join(" > ")}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-foreground/70 line-clamp-2 leading-relaxed">
                      {source.content.slice(0, 150)}
                      {source.content.length > 150 ? "..." : ""}
                    </p>
                    {debugMode && (
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-[8px] px-1 py-0.5 rounded bg-muted font-mono text-muted-foreground/70">
                          score: {source.score.toFixed(3)}
                        </span>
                        <span className="text-[8px] px-1 py-0.5 rounded font-medium bg-blue-400/15 text-blue-400">
                          {source.source_type || "vector"}
                        </span>
                      </div>
                    )}
                  </button>
                  {messageId && (
                    <div className="absolute right-2 top-1.5">
                      <SourceRatingButtons
                        sourceIndex={String(source.index)}
                        currentRating={ratings[String(source.index)]}
                        onRate={handleRate}
                      />
                    </div>
                  )}
                </div>
              ))}
              {kgSources.map((source) => (
                <div
                  key={source.chunk_id}
                  className="relative hover:bg-purple-400/5 hover:bg-muted/50 transition-colors"
                >
                  <button
                    type="button"
                    onClick={() => activateCitationKG(source, [])}
                    className={cn("w-full text-left px-2.5 py-2", messageId && "pr-[4.75rem]")}
                  >
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold rounded-full bg-purple-400/15 text-purple-400">
                        {source.index}
                      </span>
                      <span className="text-[10px] text-purple-400 font-medium">
                        知识图谱
                      </span>
                    </div>
                    <p className="text-[11px] text-foreground/70 line-clamp-2 leading-relaxed">
                      {source.content.slice(0, 150)}
                      {source.content.length > 150 ? "..." : ""}
                    </p>
                    {debugMode && (
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-[8px] px-1 py-0.5 rounded bg-muted font-mono text-muted-foreground/70">
                          评分：{source.score.toFixed(3)}
                        </span>
                        <span className="text-[8px] px-1 py-0.5 rounded font-medium bg-purple-400/15 text-purple-400">
                          kg
                        </span>
                      </div>
                    )}
                  </button>
                  {messageId && (
                    <div className="absolute right-2 top-1.5">
                      <SourceRatingButtons
                        sourceIndex={String(source.index)}
                        currentRating={ratings[String(source.index)]}
                        onRate={handleRate}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 图片引用面板 —— 在聊天中展示检索到的图片
// ---------------------------------------------------------------------------
function ImageRefCard({ img }: { img: ChatImageRef }) {
  const { activateImageCitation } = useWorkspaceStore();
  const doc = useFindDoc(img.document_id);
  return (
    <button
      onClick={() => activateImageCitation(img, doc)}
      className="group block rounded-md overflow-hidden border bg-background hover:border-primary/50 transition-colors text-left cursor-pointer"
    >
      <img
        src={img.url}
        alt={img.caption || `来自第 ${img.page_no} 页的图片`}
        className="w-full h-auto max-h-[200px] object-contain bg-white"
        loading="lazy"
      />
      {img.caption && (
        <p className="px-2 py-1 text-[10px] text-muted-foreground leading-tight line-clamp-2 border-t">
          p.{img.page_no} — {img.caption}
        </p>
      )}
    </button>
  );
}

function ImageRefsPanel({ images }: { images: ChatImageRef[] }) {
  const [expanded, setExpanded] = useState(true);

  if (images.length === 0) return null;

  return (
    <div className="mt-2 rounded-md border bg-muted/20 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <ImageIcon className="w-3 h-3" />
        文档中的 {images.length} 张图片
        <span className="ml-auto text-[10px]">{expanded ? "▲" : "▼"}</span>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="p-2 grid gap-2" style={{ gridTemplateColumns: images.length === 1 ? "1fr" : "repeat(auto-fit, minmax(140px, 1fr))" }}>
              {images.map((img) => (
                <ImageRefCard key={img.image_id} img={img} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 思考面板 —— 可折叠的紫色主题思考过程展示
// ---------------------------------------------------------------------------
function ThinkingPanel({ thinking }: { thinking: string }) {
  const [expanded, setExpanded] = useState(false);

  if (!thinking) return null;

  return (
    <div className="mt-1.5 mb-1 rounded-md border border-violet-500/20 bg-violet-500/5 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-medium text-violet-400 hover:text-violet-300 [[data-theme='light']_&]:text-violet-600 [[data-theme='light']_&]:hover:text-violet-700 transition-colors"
      >
        <Brain className="w-3 h-3" />
        思考过程
        <ChevronDown
          className={cn(
            "w-3 h-3 ml-auto transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="px-2.5 pb-2 border-t border-violet-500/10">
              <pre className="text-[11px] text-violet-300/90 [[data-theme='light']_&]:text-violet-700/90 whitespace-pre-wrap leading-relaxed mt-1.5 max-h-[300px] overflow-y-auto">
                {thinking}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 复制消息操作 —— 纯文本或原始 Markdown（不含引用）
// ---------------------------------------------------------------------------
const CITATION_STRIP_RE = /\s*\[(?:[a-z0-9]+|IMG-[a-z0-9]+)(?:,\s*(?:[a-z0-9]+|IMG-[a-z0-9]+))*\]/g;

/** 移除类似 [a3x9]、[IMG-p4f2]、[a3x9, b2m7] 的引用 */
function stripCitations(md: string): string {
  return md.replace(CITATION_STRIP_RE, "").replace(/\n{3,}/g, "\n\n").trim();
}

/** 将 Markdown 转换为纯文本：移除格式、链接、图片和代码围栏 */
function markdownToPlainText(md: string): string {
  let text = stripCitations(md);
  text = text.replace(/```[\s\S]*?```/g, (m) => {
    const lines = m.split("\n");
    return lines.slice(1, -1).join("\n");
  });
  text = text.replace(/`([^`]+)`/g, "$1");
  text = text.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  text = text.replace(/\*\*(.+?)\*\*/g, "$1");
  text = text.replace(/\*(.+?)\*/g, "$1");
  text = text.replace(/__(.+?)__/g, "$1");
  text = text.replace(/_(.+?)_/g, "$1");
  text = text.replace(/^#{1,6}\s+/gm, "");
  text = text.replace(/^[-*_]{3,}\s*$/gm, "");
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}

function CopyMessageActions({ content }: { content: string }) {
  const [copiedMode, setCopiedMode] = useState<"text" | "markdown" | null>(null);

  const handleCopy = useCallback(
    (mode: "text" | "markdown") => {
      const value =
        mode === "text" ? markdownToPlainText(content) : stripCitations(content);
      navigator.clipboard.writeText(value).then(() => {
        setCopiedMode(mode);
        setTimeout(() => setCopiedMode(null), 2000);
      });
    },
    [content]
  );

  return (
    <div className="flex items-center gap-0.5 mt-1.5">
      <button
        onClick={() => handleCopy("text")}
        className="flex items-center gap-1 px-1.5 py-0.5 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/60 transition-all text-[10px]"
        title="复制为纯文本"
      >
        {copiedMode === "text" ? (
          <ClipboardCheck className="w-3 h-3 text-emerald-500" />
        ) : (
          <Copy className="w-3 h-3" />
        )}
        <span>{copiedMode === "text" ? "已复制！" : "复制文本"}</span>
      </button>
      <button
        onClick={() => handleCopy("markdown")}
        className="flex items-center gap-1 px-1.5 py-0.5 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/60 transition-all text-[10px]"
        title="复制为 Markdown"
      >
        {copiedMode === "markdown" ? (
          <ClipboardCheck className="w-3 h-3 text-emerald-500" />
        ) : (
          <FileCode className="w-3 h-3" />
        )}
        <span>{copiedMode === "markdown" ? "已复制！" : "复制 Markdown"}</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 单条消息气泡
// ---------------------------------------------------------------------------
const MessageBubble = memo(function MessageBubble({
  message,
}: {
  message: ChatMessage;
}) {
  const isUser = message.role === "user";
  const reduceMotion = useReducedMotion();

  const proseClasses = cn(
    "prose prose-sm max-w-none text-foreground/90",
    "[&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5",
    "[&_pre]:bg-transparent [&_pre]:border-none [&_pre]:p-0 [&_pre]:m-0",
    "[&_code]:bg-muted/50 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-xs [&_code]:text-foreground/90",
    "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
    "[&_strong]:text-foreground [&_em]:text-foreground/80",
    "[&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_h4]:text-foreground",
    "[&_h1]:text-base [&_h1]:font-bold [&_h1]:mt-3 [&_h1]:mb-1",
    "[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-2.5 [&_h2]:mb-1",
    "[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-0.5",
    "[&_blockquote]:border-l-2 [&_blockquote]:border-primary/30 [&_blockquote]:pl-3 [&_blockquote]:italic [&_blockquote]:text-foreground/60",
    "[&_table]:text-xs [&_th]:px-2 [&_th]:py-1 [&_td]:px-2 [&_td]:py-1 [&_th]:text-foreground/80 [&_td]:text-foreground/80",
    "[&_li]:text-foreground/90",
    "[&_.katex-display]:overflow-x-auto [&_.katex-display]:py-2",
    "[&_.katex]:text-[0.9em]"
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduceMotion ? FADE_REDUCED : SPRING_PANEL}
      className={cn("flex gap-2", isUser ? "justify-end" : "justify-start")}
    >
      {/* 助手：流式输出期间显示带光环的机器人图标 */}
      {!isUser && (
        <div className="relative w-6 h-6 flex-shrink-0 mt-1">
          {message.isStreaming && <div className="icon-glow-ring" />}
          <div className="w-6 h-6 rounded-full bg-primary/15 flex items-center justify-center">
            <Bot className="w-3.5 h-3.5 text-primary" />
          </div>
        </div>
      )}

      <div
        className={cn(
          isUser
            ? "max-w-[85%] rounded-xl px-3 py-2 bg-secondary/50"
            : "max-w-[90%] min-w-0 py-1"
        )}
      >
        {/* ThinkingTimeline —— 单实例，在流式输出到完成的切换期间不卸载 */}
        {!isUser && message.agentSteps && message.agentSteps.length > 0 && (
          <ThinkingTimeline
            steps={message.agentSteps}
            mode={message.isStreaming ? "live" : "embedded"}
            className={cn("mb-1.5", message.isStreaming && "mt-1")}
            autoCollapse={message.isStreaming && !!message.content}
          />
        )}

        {/* 输入指示器 —— 仅在流式输出且尚无步骤和内容时显示 */}
        {!isUser && message.isStreaming && !message.content && !message.agentSteps?.length && (
          <TypingIndicator status="analyzing" />
        )}

        {isUser ? (
          <p className="text-sm leading-relaxed whitespace-pre-wrap">
            {message.content}
          </p>
        ) : message.isStreaming ? (
          message.content ? (
            <div
              className={cn(proseClasses, "relative")}
              style={{
                maskImage: "linear-gradient(to bottom, black calc(100% - 80px), transparent 100%)",
                WebkitMaskImage: "linear-gradient(to bottom, black calc(100% - 80px), transparent 100%)",
              }}
            >
              <StreamingMarkdown
                content={message.content}
                isStreaming
                renderBlock={(block) => (
                  <MarkdownWithCitations
                    content={block}
                    sources={message.sources || []}
                    relatedEntities={message.relatedEntities || []}
                    imageRefs={message.imageRefs}
                  />
                )}
              />
              <span className="streaming-cursor" />
            </div>
          ) : message.thinking ? (
            <InlineThinkingPreview text={message.thinking} />
          ) : null
        ) : (
          <div className={proseClasses}>
            <MarkdownWithCitations
              content={message.content}
              sources={message.sources || []}
              relatedEntities={message.relatedEntities || []}
              imageRefs={message.imageRefs}
            />
          </div>
        )}

        {/* 助手消息的复制操作 */}
        {!isUser && message.content && (
          <CopyMessageActions content={message.content} />
        )}

        {/* ThinkingPanel —— 仅在不存在带思考日志的 ThinkingTimeline 时显示（避免重复） */}
        {!isUser && message.thinking && !message.isStreaming &&
          !message.agentSteps?.some((s) => s.thinkingText) && (
          <ThinkingPanel thinking={message.thinking} />
        )}

        {!isUser && !message.isStreaming && message.sources && message.sources.length > 0 && (
          <SourcesPanel sources={message.sources} messageId={message.id} />
        )}

        {!isUser && !message.isStreaming && message.imageRefs && message.imageRefs.length > 0 && (
          <ImageRefsPanel images={message.imageRefs} />
        )}

        <p
          className={cn(
            "text-[9px] mt-1",
            isUser ? "text-muted-foreground/50" : "text-muted-foreground/50"
          )}
        >
          {new Date(message.timestamp).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>

      {isUser && (
        <div className="w-6 h-6 rounded-full bg-secondary flex items-center justify-center flex-shrink-0 mt-1">
          <User className="w-3.5 h-3.5 text-muted-foreground" />
        </div>
      )}
    </motion.div>
  );
});

// ---------------------------------------------------------------------------
// 内联思考预览 —— 模型思考时显示在消息正文中
// ---------------------------------------------------------------------------

function InlineThinkingPreview({ text }: { text: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledRef = useRef(false);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
    isUserScrolledRef.current = !isAtBottom;
  }, []);

  useEffect(() => {
    if (containerRef.current && !isUserScrolledRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [text]);

  return (
    <div className="mt-1">
      <div className="flex items-center gap-1.5 mb-1.5">
        <Brain className="w-3.5 h-3.5 text-violet-400 animate-pulse" />
        <span className="text-xs font-medium text-violet-400">思考中...</span>
      </div>
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className={cn(
          "text-xs leading-relaxed text-muted-foreground/70 italic",
          "max-h-[200px] overflow-y-auto scrollbar-none",
          "border-l-2 border-violet-500/30 pl-3",
          "whitespace-pre-wrap break-words",
        )}
      >
        {text}
        <span className="animate-pulse text-violet-400 ml-0.5">|</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 输入指示器
// ---------------------------------------------------------------------------
const STATUS_LABELS: Record<string, string> = {
  analyzing: "正在分析你的问题...",
  retrieving: "正在搜索文档...",
  generating: "正在生成回答...",
};

function TypingIndicator({ status }: { status?: ChatStreamStatus }) {
  const label = (status && STATUS_LABELS[status]) || "正在分析文档...";
  return (
    <div className="flex gap-2 items-start">
      <div className="relative w-6 h-6 flex-shrink-0">
        <div className="icon-glow-ring" />
        <div className="w-6 h-6 rounded-full bg-primary/15 flex items-center justify-center">
          <Bot className="w-3.5 h-3.5 text-primary" />
        </div>
      </div>
      <div className="py-1">
        <div className="flex items-center gap-1.5">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
          <span className="text-xs text-muted-foreground">{label}</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 建议标签（空状态）
// ---------------------------------------------------------------------------
function SuggestionChips({
  onSelect,
}: {
  onSelect: (q: string) => void;
}) {
  const suggestions = [
    "总结关键发现",
    "有哪些主要主题？",
    "列出提到的重点实体",
    "解释使用的方法论",
  ];

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4">
      <div className="workspace-empty-icon mb-4">
        <Sparkles className="w-6 h-6 text-primary" />
      </div>
      <h3 className="text-sm font-semibold mb-1">AI 文档助手</h3>
      <p className="mb-4 max-w-[260px] text-center text-xs leading-relaxed text-muted-foreground">
        选择一个常用问题，或在下方直接询问你的文档。
      </p>
      <div className="flex max-w-[340px] flex-wrap justify-center gap-1.5">
        {suggestions.map((s) => (
          <button
            type="button"
            key={s}
            onClick={() => onSelect(s)}
            className="ui-button rounded-full border bg-card px-3 py-1.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChatPanel —— 主导出
// ---------------------------------------------------------------------------
const DEFAULT_SYSTEM_PROMPT =
  "You are a document Q&A assistant. Your goal is to write an accurate, " +
  "detailed, and comprehensive answer to the user's question, drawing from " +
  "the provided document sources. You will be given retrieved document sources " +
  "from a knowledge base to help you answer. Your answer should be informed by " +
  "these provided sources. Your answer must be self-contained and respond fully " +
  "to the question. Your answer must be correct, high-quality, well-formatted, " +
  "and written by an expert using an unbiased and journalistic tone.\n\n" +
  "## Core Behavior\n" +
  "- Answer questions ONLY using the provided document sources. " +
  "Do NOT add any information from your own knowledge.\n" +
  "- Extract ALL relevant information from sources: numbers, percentages, " +
  "dates, names, statistics, data from tables, and specific details.\n" +
  "- You may synthesize, compare, and draw logical conclusions from " +
  "multiple sources when the question requires it.\n" +
  "- If sources contain partial information, use what is available and " +
  "clearly note what is missing.\n" +
  "- When asked about specific data, always provide exact numbers rather " +
  "than vague descriptions.\n\n" +
  "## Question Type Handling\n\n" +
  "**Factual / Data:** Direct answers with exact figures, percentages, " +
  "time periods. Present multi-row data in tables.\n\n" +
  "**Comparison / Analysis:** Use Markdown tables for side-by-side comparisons. " +
  "Draw logical conclusions from data.\n\n" +
  "**Technical / Academic:** Long detailed answers with sections and headings. " +
  "Include formulas (LaTeX), code blocks.\n\n" +
  "**Summary:** Organize by themes, not by source document. " +
  "Highlight key findings.\n\n" +
  "**Coding:** Use ```language code blocks. Code first, explain after.\n\n" +
  "**Science / Math:** Include formulas in LaTeX. For simple calculations, " +
  "answer with final result.\n\n" +
  "## Reasoning\n" +
  "- Determine question type and apply appropriate handling.\n" +
  "- Break complex questions into sub-questions.\n" +
  "- A partial correct answer is better than a complete wrong one.\n" +
  "- Make sure your answer addresses ALL parts of the question.\n\n" +
  "## Response Quality\n" +
  "- Prioritize accuracy over completeness.\n" +
  "- When sources conflict, acknowledge and present both perspectives.\n" +
  "- NEVER say 'information not found' when data IS present in any source.\n" +
  "- If the premise is incorrect based on sources, explain why.";

// 始终附加的硬性规则 —— 在提示中显示，不可编辑
const HARD_RULES_SUMMARY = [
  // 语言（强制）
  "必须使用与用户提问相同的语言回答。",
  // 引用
  "每个观点都要引用：[a3x9][b2m7]，引用前不要留空格。",
  "图片：[IMG-p4f2][IMG-q7r3]，不要合并或混用括号。",
  "每句话最多 3 个引用，结尾不要添加参考文献列表。",
  // 格式
  "先给摘要，绝不使用标题或“基于...”开头。",
  "使用 ## 分节、表格做对比、只使用平铺列表。",
  "公式用 LaTeX：$行内$ 和 $$块级$$，数学公式不要使用 Unicode。",
  "代码块用 ```语言，引用用 >，重点词用 **加粗**。",
  // 限制
  "不要含糊（如“重要的是...”），直接给出答案。",
  "不要使用表情符号，结尾不要提问。",
];

interface ChatPanelProps {
  workspaceId: string;
  hasIndexedDocs: boolean;
  workspace: KnowledgeBase | null;
}

export const ChatPanel = memo(function ChatPanel({
  workspaceId,
  hasIndexedDocs,
  workspace,
}: ChatPanelProps) {
  const reduceMotion = useReducedMotion();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [enableThinking, setEnableThinking] = useState(false);
  const [thinkingDefaultSynced, setThinkingDefaultSynced] = useState(false);
  const [forceSearch, setForceSearch] = useState(false);

  // 从 PostgreSQL 加载聊天历史
  const { data: historyData, isLoading: historyLoading } = useChatHistory(workspaceId);
  const clearMutation = useClearChatHistory(workspaceId);
  const [showPromptEditor, setShowPromptEditor] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const scrollAnimRef = useRef<number | undefined>(undefined);
  const spacerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 调试模式（Ctrl+Shift+D 切换，持久化到 localStorage）
  const [debugMode, setDebugMode] = useState(() =>
    localStorage.getItem("myrag-debug-mode") === "true",
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === "D") {
        e.preventDefault();
        setDebugMode((prev) => {
          const next = !prev;
          localStorage.setItem("myrag-debug-mode", String(next));
          toast.success(next ? "调试模式已开启" : "调试模式已关闭");
          return next;
        });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // 系统提示词编辑器
  const updateWorkspaceMutation = useUpdateWorkspace();
  const savedPrompt = workspace?.system_prompt ?? "";
  const effectivePrompt = savedPrompt || DEFAULT_SYSTEM_PROMPT;
  const isCustom = !!savedPrompt;

  // 工作区数据加载或变化时同步草稿
  useEffect(() => {
    setPromptDraft(effectivePrompt);
  }, [effectivePrompt]);

  const promptIsDirty = promptDraft !== effectivePrompt;

  const handleSavePrompt = useCallback(() => {
    if (!workspace) return;
    // 如果草稿等于默认值，则保存空字符串 → 在数据库中重置为默认值
    const toSave = promptDraft.trim() === DEFAULT_SYSTEM_PROMPT ? "" : promptDraft;
    updateWorkspaceMutation.mutate(
      { id: workspace.id, data: { system_prompt: toSave } },
      { onSuccess: () => toast.success("系统提示词已保存") }
    );
  }, [workspace, promptDraft, updateWorkspaceMutation]);

  const handleResetPrompt = useCallback(() => {
    if (!workspace) return;
    setPromptDraft(DEFAULT_SYSTEM_PROMPT);
    updateWorkspaceMutation.mutate(
      { id: workspace.id, data: { system_prompt: "" } },
      { onSuccess: () => toast.success("系统提示词已重置为默认值") }
    );
  }, [workspace, updateWorkspaceMutation]);

  // 检查 LLM 能力（是否支持思考模式）
  const { data: capabilities } = useQuery<LLMCapabilities>({
    queryKey: ["llm-capabilities"],
    queryFn: () => api.get<LLMCapabilities>("/rag/capabilities"),
    staleTime: 5 * 60 * 1000, // 缓存 5 分钟
    retry: 1,
  });
  const thinkingSupported = capabilities?.supports_thinking ?? false;

  // 从服务器同步思考开关默认值（每次挂载一次）
  useEffect(() => {
    if (capabilities && !thinkingDefaultSynced) {
      setEnableThinking(capabilities.thinking_default);
      setThinkingDefaultSynced(true);
    }
  }, [capabilities, thinkingDefaultSynced]);

  // 数据加载时将数据库历史同步到本地消息状态。
  // 重要：保留本地状态中的 agentSteps —— 它们仅存在于客户端（不存入数据库）。
  // 否则流式输出后的 queryClient.invalidateQueries 会覆盖 agentSteps → ThinkingTimeline 消失。
  useEffect(() => {
    if (historyData?.messages) {
      setMessages((prev) => {
        // 按消息 ID 构建现有 agentSteps 映射，以便数据库同步后重新挂载
        const stepsMap = new Map<string, AgentStep[]>();
        for (const m of prev) {
          if (m.agentSteps?.length) stepsMap.set(m.id, m.agentSteps);
        }
        return historyData.messages.map((m) => ({
          id: m.message_id,
          role: m.role as "user" | "assistant",
          content: m.content,
          sources: m.sources ?? undefined,
          relatedEntities: m.related_entities ?? undefined,
          imageRefs: m.image_refs ?? undefined,
          thinking: m.thinking ?? undefined,
          timestamp: m.created_at,
          // 优先级：本地实时步骤（来自当前会话）> 数据库持久化的合成步骤
          agentSteps: stepsMap.get(m.message_id) ?? (m.agent_steps?.length ? m.agent_steps as AgentStep[] : undefined),
        }));
      });
    }
  }, [historyData]);

  // SSE 流式聊天
  const stream = useRAGChatStream(workspaceId);
  const streamingMsgIdRef = useRef<string | null>(null);
  // 将 agentSteps 快照到 ref，确保收尾时始终有最新数据
  const agentStepsRef = useRef<AgentStep[]>([]);
  useEffect(() => {
    if (stream.agentSteps.length > 0) {
      agentStepsRef.current = stream.agentSteps;
    }
  }, [stream.agentSteps]);

  // 双重 rAF + easeOutCubic 缓动滚动到底部
  const scrollToBottom = useCallback((smooth = true) => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // 取消正在进行的动画
    if (scrollAnimRef.current) {
      cancelAnimationFrame(scrollAnimRef.current);
      scrollAnimRef.current = undefined;
    }

    // 双重 rAF：确保在测量前完成 React 提交和浏览器绘制
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const el = scrollContainerRef.current;
        if (!el) return;
        const target = el.scrollHeight - el.clientHeight;
        if (!smooth || Math.abs(target - el.scrollTop) < 10) {
          el.scrollTop = target;
          return;
        }

        const start = el.scrollTop;
        const distance = target - start;
        const duration = 400;
        const startTime = performance.now();

        const scrollEl = el; // 为闭包捕获元素
        function animate(now: number) {
          const t = Math.min((now - startTime) / duration, 1);
          const ease = 1 - Math.pow(1 - t, 3); // easeOutCubic 缓动
          scrollEl.scrollTop = start + distance * ease;
          if (t < 1) {
            scrollAnimRef.current = requestAnimationFrame(animate);
          } else {
            scrollAnimRef.current = undefined;
          }
        }

        scrollAnimRef.current = requestAnimationFrame(animate);
      });
    });
  }, []);

  // 将用户消息滚动到聊天区域顶部
  const scrollUserMsgToTop = useCallback((msgId: string) => {
    if (scrollAnimRef.current) {
      cancelAnimationFrame(scrollAnimRef.current);
      scrollAnimRef.current = undefined;
    }
    // 双重 rAF：等待 React 提交和浏览器绘制
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        // 确保滚动前已设置占位符高度（useEffect 可能尚未执行）
        if (spacerRef.current) {
          spacerRef.current.style.height = `${container.clientHeight}px`;
        }

        const el = container.querySelector(`[data-message-id="${msgId}"]`) as HTMLElement | null;
        if (!el) return;

        // 使用 getBoundingClientRect 获取相对滚动容器的准确位置
        // （offsetTop 相对 offsetParent，而非滚动容器）
        const containerRect = container.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        const relativeTop = elRect.top - containerRect.top + container.scrollTop;

        const PADDING_TOP = 12;
        const start = container.scrollTop;
        const target = Math.max(0, relativeTop - PADDING_TOP);
        if (Math.abs(target - start) < 5) return;

        const distance = target - start;
        const duration = 380;
        const startTime = performance.now();

        function animate(now: number) {
          const t = Math.min((now - startTime) / duration, 1);
          const ease = 1 - Math.pow(1 - t, 3); // easeOutCubic 缓动
          container!.scrollTop = start + distance * ease;
          if (t < 1) {
            scrollAnimRef.current = requestAnimationFrame(animate);
          } else {
            scrollAnimRef.current = undefined;
          }
        }
        scrollAnimRef.current = requestAnimationFrame(animate);
      });
    });
  }, []);

  // 保持占位符高度 = 容器高度，使用户消息始终可以滚动到顶部
  const hasMessages = messages.length > 0;
  useEffect(() => {
    if (!hasMessages) return;
    const container = scrollContainerRef.current;
    if (!container) return;

    const updateSpacer = () => {
      if (spacerRef.current) {
        spacerRef.current.style.height = `${container.clientHeight}px`;
      }
    };
    updateSpacer();
    const observer = new ResizeObserver(updateSpacer);
    observer.observe(container);
    return () => observer.disconnect();
  }, [hasMessages]);

  // 流式输出结束时重置占位符；跟踪状态以避免误触发 scrollToBottom
  const prevIsStreamingRef = useRef(false);
  const justFinishedStreamingRef = useRef(false);
  useEffect(() => {
    if (prevIsStreamingRef.current && !stream.isStreaming) {
      // 流式输出刚结束：重置占位符并标记，让 scrollToBottom 跳过本轮
      if (spacerRef.current) {
        spacerRef.current.style.height = "0px";
      }
      justFinishedStreamingRef.current = true;
    }
    prevIsStreamingRef.current = stream.isStreaming;
  }, [stream.isStreaming]);

  // 仅在非流式消息变化时自动滚动（如历史加载等）
  // 流式输出刚结束时跳过 —— 视口已显示 AI 回答的结尾
  useEffect(() => {
    if (!stream.isStreaming) {
      if (justFinishedStreamingRef.current) {
        justFinishedStreamingRef.current = false;
        return;
      }
      scrollToBottom();
    }
  }, [messages, stream.isStreaming, scrollToBottom]);

  // 将流式内容和 agentSteps 同步到流式消息的状态
  useEffect(() => {
    if (!stream.isStreaming || !streamingMsgIdRef.current) return;
    const id = streamingMsgIdRef.current;
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === id);
      if (idx === -1) return prev;
      const m = prev[idx];

      // 如果没有任何实际变化则直接返回 —— 防止无限重渲染
      const newContent = stream.streamingContent;
      const newSources = stream.pendingSources.length > 0 ? stream.pendingSources : m.sources;
      const newImages = stream.pendingImages.length > 0 ? stream.pendingImages : m.imageRefs;
      const newThinking = stream.thinkingText || m.thinking;
      const newSteps = stream.agentSteps.length > 0 ? stream.agentSteps : m.agentSteps;

      if (
        m.content === newContent &&
        m.sources === newSources &&
        m.imageRefs === newImages &&
        m.thinking === newThinking &&
        m.agentSteps === newSteps
      ) {
        return prev; // 无变化 → 跳过 setMessages 重渲染
      }

      const updated = [...prev];
      updated[idx] = {
        ...m,
        content: newContent,
        sources: newSources,
        imageRefs: newImages,
        thinking: newThinking,
        agentSteps: newSteps,
      };
      return updated;
    });
  }, [stream.streamingContent, stream.pendingSources, stream.pendingImages, stream.thinkingText, stream.isStreaming, stream.agentSteps]);

  const handleSend = useCallback(
    async (text?: string) => {
      const msg = (text || input).trim();
      if (!msg || stream.isStreaming) return;

      const userMsg: ChatMessage = {
        id: generateId(),
        role: "user",
        content: msg,
        timestamp: new Date().toISOString(),
      };

      // 为流式输出添加占位助手消息
      const assistantId = generateId();
      streamingMsgIdRef.current = assistantId;
      const placeholderMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMsg, placeholderMsg]);
      setInput("");
      // 将新用户消息滚动到顶部，让助手回答填充下方空间
      scrollUserMsgToTop(userMsg.id);

      // 从之前的消息构建历史（排除新用户消息和占位消息）
      const history = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const finalMsg = await stream.sendMessage(
        msg,
        history,
        thinkingSupported && enableThinking,
        forceSearch,
      );

      // 收尾流式消息（优先使用 finalMsg.agentSteps —— 直接来自 SSE 循环，
      // 其次回退到 ref 快照，最后使用流式期间同步到消息中的步骤）
      if (finalMsg) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...finalMsg,
                  id: assistantId,
                  isStreaming: false,
                  agentSteps: finalMsg.agentSteps?.length
                    ? finalMsg.agentSteps
                    : agentStepsRef.current.length > 0
                      ? agentStepsRef.current
                      : m.agentSteps,
                }
              : m,
          ),
        );
      } else if (stream.error) {
        toast.error("聊天失败：" + stream.error);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: m.content || "抱歉，我遇到了错误，请重试。",
                  isStreaming: false,
                }
              : m,
          ),
        );
      } else {
        // 已取消 —— 保留部分内容
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false } : m,
          ),
        );
      }
      streamingMsgIdRef.current = null;
    },
    [input, messages, stream, thinkingSupported, enableThinking],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    setMessages([]);
    clearMutation.mutate();
    useWorkspaceStore.getState().clearHighlights();
  };

  // 收集所有助手消息的来源，作为引用回退。
  // 当模型未调用 search_documents 却引用了之前回答中的引用 ID 时，
  // 这些来源仍能渲染为链接。
  // 注意：必须在任何提前返回之前声明，以满足 Hooks 规则。
  const allSources = useMemo(() => {
    const seen = new Set<string>();
    const merged: ChatSourceChunk[] = [];
    for (const m of messages) {
      if (m.role === "assistant" && m.sources) {
        for (const s of m.sources) {
          const key = String(s.index);
          if (!seen.has(key)) {
            seen.add(key);
            merged.push(s);
          }
        }
      }
    }
    return merged;
  }, [messages]);

  if (historyLoading) {
    return (
      <section className="workspace-panel h-full min-w-0" aria-label="AI 助手">
        <header className="workspace-panel-header">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">AI 助手</span>
          </div>
        </header>
        <div className="workspace-empty-state flex-1" role="status">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <p className="mt-2 text-xs text-muted-foreground">正在恢复对话...</p>
        </div>
      </section>
    );
  }

  if (!hasIndexedDocs) {
    return (
      <section className="workspace-panel h-full min-w-0" aria-label="AI 助手">
        <header className="workspace-panel-header">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">AI 助手</span>
          </div>
        </header>
        <div className="workspace-empty-state flex-1 px-4">
          <div className="workspace-empty-icon mb-3">
            <Bot className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-foreground/80">先准备一篇文档</p>
          <p className="mt-1 max-w-[230px] text-center text-[11px] leading-relaxed text-muted-foreground">
            上传文档并完成分析后，这里会立即开放提问。
          </p>
        </div>
      </section>
    );
  }

  return (
    <WsIdCtx.Provider value={workspaceId}>
    <DebugCtx.Provider value={debugMode}>
    <AllSourcesCtx.Provider value={allSources}>
    <section className="workspace-panel h-full min-w-0" aria-label="AI 助手">
      {/* 头部 */}
      <header className="workspace-panel-header px-3">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">AI 助手</span>
        </div>
        <div className="flex items-center gap-0.5">
          {/* 思考开关 —— 仅当模型支持思考时显示 */}
          {thinkingSupported && (
            <button
              type="button"
              aria-pressed={enableThinking}
              onClick={() => setEnableThinking((prev) => !prev)}
              className={cn(
                "ui-button flex h-7 items-center gap-1 rounded-lg px-2 text-[10px] transition-colors",
                enableThinking
                  ? "text-violet-400 bg-violet-400/10 hover:bg-violet-400/15"
                  : "text-muted-foreground hover:bg-muted"
              )}
              title={enableThinking ? "思考模式已开启" : "思考模式已关闭"}
            >
              <Brain className="w-3 h-3" />
              <span>思考</span>
            </button>
          )}
          {/* 强制搜索开关 */}
          <button
            type="button"
            aria-pressed={forceSearch}
            onClick={() => setForceSearch((prev) => !prev)}
            className={cn(
              "ui-button flex h-7 items-center gap-1 rounded-lg px-2 text-[10px] transition-colors",
              forceSearch
                ? "text-amber-500 bg-amber-500/10 hover:bg-amber-500/15"
                : "text-muted-foreground hover:bg-muted"
            )}
            title={forceSearch ? "强制搜索已开启 — 每次回答前都会预检索" : "强制搜索已关闭 — 由 AI 决定是否搜索"}
          >
            <DatabaseZap className="w-3 h-3" />
            <span>搜索</span>
          </button>
          {/* 系统提示词设置 */}
          <button
            type="button"
            aria-pressed={showPromptEditor}
            onClick={() => setShowPromptEditor((p) => !p)}
            className={cn(
              "app-icon-button h-7 w-7 transition-colors",
              showPromptEditor
                ? "text-blue-500 bg-blue-500/10 hover:bg-blue-500/15"
                : "text-muted-foreground hover:bg-muted"
            )}
            title="系统提示词设置"
          >
            <Settings className="w-3 h-3" />
          </button>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={handleClear}
              className="app-icon-button h-7 w-7 transition-colors"
              title="清空聊天"
              aria-label="清空聊天"
            >
              <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
            </button>
          )}
          {debugMode && (
            <span className="text-[8px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-500 font-mono font-semibold">
              DEBUG
            </span>
          )}
        </div>
      </header>

      {/* 系统提示词编辑器 */}
      <AnimatePresence>
        {showPromptEditor && (
          <motion.div
            initial={reduceMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={reduceMotion ? MOTION_INSTANT : SPRING_PANEL}
            className="relative z-10 flex-shrink-0 overflow-visible border-b"
          >
            <div className="px-3 py-2 space-y-2 bg-muted/20">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-muted-foreground">
                  系统提示词
                </span>
                <span className={cn(
                  "text-[9px] px-1.5 py-0.5 rounded-full font-medium",
                  isCustom
                    ? "bg-blue-500/15 text-blue-600 dark:text-blue-400"
                    : "bg-muted text-muted-foreground/50"
                )}>
                  {isCustom ? "自定义" : "默认"}
                </span>
              </div>
              <textarea
                value={promptDraft}
                onChange={(e) => setPromptDraft(e.target.value)}
                placeholder="输入自定义系统提示词..."
                rows={8}
                className={cn(
                  "w-full resize-none rounded-md border border-input bg-background px-2.5 py-2 text-xs",
                  "placeholder:text-muted-foreground/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  "leading-relaxed"
                )}
              />
              {/* 硬性规则 —— 图标带悬停提示 */}
              <div className="flex items-center gap-1.5">
                <div className="relative group/cite">
                  <div className="flex items-center gap-1 cursor-help">
                    <Info className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                    <span className="text-[10px] text-blue-600 dark:text-blue-400 font-medium">
                      自动附加硬性规则
                    </span>
                  </div>
                  {/* 悬停提示 —— 显示在图标下方 */}
                  <div className="absolute left-0 top-full z-50 mt-1.5 w-[min(340px,calc(100vw-2rem))] rounded-xl border border-border bg-card shadow-xl opacity-0 pointer-events-none group-hover/cite:opacity-100 group-hover/cite:pointer-events-auto transition-opacity duration-150">
                    <div className="px-3 py-2.5">
                      <p className="text-[10px] font-semibold text-blue-700 dark:text-blue-300 mb-1.5">
                        引用 + 格式 + 限制（始终生效）
                      </p>
                      <ul className="space-y-1">
                        {HARD_RULES_SUMMARY.map((rule, i) => (
                          <li key={i} className="text-[10px] text-foreground/70 leading-snug flex gap-1">
                            <span className="text-blue-500 dark:text-blue-400 flex-shrink-0">•</span>
                            {rule}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5 justify-end">
                <button
                  onClick={handleResetPrompt}
                  disabled={!isCustom && !promptIsDirty}
                  className={cn(
                    "flex items-center gap-1 px-2 py-1 rounded text-[10px] transition-colors",
                    isCustom || promptIsDirty
                      ? "text-muted-foreground hover:bg-muted hover:text-foreground"
                      : "text-muted-foreground/30 cursor-not-allowed"
                  )}
                  title="重置为默认提示词"
                >
                  <RotateCcw className="w-3 h-3" />
                  重置
                </button>
                <button
                  onClick={handleSavePrompt}
                  disabled={!promptIsDirty || updateWorkspaceMutation.isPending}
                  className={cn(
                    "flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium transition-colors",
                    promptIsDirty && !updateWorkspaceMutation.isPending
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "bg-muted text-muted-foreground/50 cursor-not-allowed"
                  )}
                >
                  {updateWorkspaceMutation.isPending ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Save className="w-3 h-3" />
                  )}
                  保存
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 消息区域 */}
      {messages.length === 0 ? (
        <SuggestionChips onSelect={handleSend} />
      ) : (
        <div ref={scrollContainerRef} className="relative flex-1 min-h-0 space-y-3 overflow-y-auto px-4 py-4">
          <AnimatePresence>
            {messages.map((msg) => (
              <div key={msg.id} data-message-id={msg.id}>
                <MessageBubble message={msg} />
              </div>
            ))}
          </AnimatePresence>
          {/* ThinkingTimeline + TypingIndicator 现在在 MessageBubble 内部渲染 */}
          {/* 底部占位符 = 容器高度，支持用户消息滚动到顶部 */}
          <div ref={spacerRef} aria-hidden />
        </div>
      )}

      {/* 输入区域 */}
      <div className="chat-composer-shell flex-shrink-0 border-t px-3 pb-2 pt-2.5">
        <div className="chat-composer flex items-end gap-2 rounded-2xl border bg-card p-1.5">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="询问你的文档..."
            aria-label="向文档提问"
            rows={1}
            className={cn(
              "flex-1 resize-none rounded-xl border-0 bg-transparent px-2.5 py-2 text-sm",
              "placeholder:text-muted-foreground focus-visible:outline-none",
              "max-h-[120px] min-h-[36px]"
            )}
            style={{
              height: "auto",
              minHeight: "36px",
            }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = Math.min(target.scrollHeight, 120) + "px";
            }}
          />
          <button
            type="button"
            onClick={stream.isStreaming ? stream.cancel : () => handleSend()}
            disabled={!stream.isStreaming && !input.trim()}
            className={cn(
              "ui-button flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl transition-colors",
              stream.isStreaming
                ? "bg-destructive/15 text-destructive hover:bg-destructive/25"
                : input.trim()
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "bg-muted text-muted-foreground cursor-not-allowed"
            )}
            title={stream.isStreaming ? "停止生成" : "发送消息"}
            aria-label={stream.isStreaming ? "停止生成" : "发送消息"}
          >
            {stream.isStreaming ? (
              <Square className="h-3.5 w-3.5 fill-current" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
        <p className="mt-1.5 h-3 text-center text-[9px] text-muted-foreground/60" aria-live="polite">
          {stream.isStreaming ? "正在生成，可随时停止" : "Enter 发送 · Shift+Enter 换行"}
        </p>
      </div>
    </section>
    </AllSourcesCtx.Provider>
    </DebugCtx.Provider>
    </WsIdCtx.Provider>
  );
});
