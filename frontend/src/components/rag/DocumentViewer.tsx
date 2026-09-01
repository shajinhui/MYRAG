import { useState, useEffect, useRef, useMemo, useCallback, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { FileText, List, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { Document, ChatSourceChunk } from "@/types";

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------
interface Heading {
  id: string;
  text: string;
  level: number;
}

// ---------------------------------------------------------------------------
// 骨架屏加载器
// ---------------------------------------------------------------------------
function ViewerSkeleton() {
  return (
    <div className="p-6 space-y-4 animate-pulse">
      <div className="h-6 bg-muted rounded w-3/5" />
      <div className="h-4 bg-muted rounded w-full" />
      <div className="h-4 bg-muted rounded w-4/5" />
      <div className="h-4 bg-muted rounded w-full" />
      <div className="h-4 bg-muted rounded w-2/3" />
      <div className="h-20 bg-muted rounded w-full mt-4" />
      <div className="h-4 bg-muted rounded w-full" />
      <div className="h-4 bg-muted rounded w-3/4" />
      <div className="h-4 bg-muted rounded w-full" />
      <div className="h-4 bg-muted rounded w-1/2" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 错误状态
// ---------------------------------------------------------------------------
function ViewerError({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <FileText className="w-10 h-10 text-muted-foreground/40 mb-3" />
      <p className="text-sm font-medium">无法加载文档</p>
      <p className="text-xs text-muted-foreground mt-1 max-w-xs">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 空状态
// ---------------------------------------------------------------------------
function ViewerEmpty() {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <FileText className="w-10 h-10 text-muted-foreground/30 mb-3" />
      <p className="text-sm text-muted-foreground">
        该文档暂无可用解析内容
      </p>
      <p className="text-xs text-muted-foreground/60 mt-1">
        文档可能尚未使用 MYRAG 处理
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 目录侧边栏
// ---------------------------------------------------------------------------
const TOCSidebar = memo(function TOCSidebar({
  headings,
  activeId,
  onSelect,
}: {
  headings: Heading[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  if (headings.length === 0) return null;

  return (
    <nav className="hidden w-52 flex-shrink-0 overflow-y-auto border-r px-2 py-3 2xl:block">
      <div className="flex items-center gap-1.5 px-2 mb-2">
        <List className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">目录</span>
      </div>
      <ul className="space-y-0.5">
        {headings.map((h, index) => (
          <li key={`${h.id}-${index}`}>
            <button
              onClick={() => onSelect(h.id)}
              className={cn(
                "w-full text-left text-xs py-1 px-2 rounded-md transition-colors truncate",
                "hover:bg-muted",
                activeId === h.id
                  ? "text-primary font-medium bg-primary/10"
                  : "text-muted-foreground"
              )}
              style={{ paddingLeft: `${(h.level - 1) * 12 + 8}px` }}
              title={h.text}
            >
              {h.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
});

// ---------------------------------------------------------------------------
// 页面分隔线 —— 插入到 Markdown 的页面之间
// ---------------------------------------------------------------------------
function PageDivider({ pageNo }: { pageNo: number }) {
  return (
    <div className="flex items-center gap-3 py-4 select-none" data-page={pageNo}>
      <div className="flex-1 border-t border-dashed border-muted-foreground/20" />
      <span className="text-[10px] font-medium text-muted-foreground/50 uppercase tracking-wider">
        第 {pageNo} 页
      </span>
      <div className="flex-1 border-t border-dashed border-muted-foreground/20" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 从 Markdown 中提取标题，用于生成目录
// ---------------------------------------------------------------------------
function extractHeadings(markdown: string): Heading[] {
  const headings: Heading[] = [];
  const lines = markdown.split("\n");
  for (const line of lines) {
    const match = line.match(/^(#{1,4})\s+(.+)/);
    if (match) {
      const level = match[1].length;
      const text = match[2].replace(/[*_`#]/g, "").trim();
      const id = generateHeadingId(text);
      headings.push({ id, text, level });
    }
  }
  return headings;
}

// ---------------------------------------------------------------------------
// 在 Markdown 文本中插入页面分隔线
// ---------------------------------------------------------------------------
function insertPageDividers(markdown: string): string {
  // Docling 会插入类似 "<!-- page 3 -->" 或 "---\n\n## Page 3" 的页标记
  // 我们将它们规范化为自定义标记进行渲染
  return markdown.replace(
    /(?:<!--\s*page\s+(\d+)\s*-->|(?:^|\n)---+\s*\n+(?=##?\s))/gi,
    (match, pageNo) => {
      if (pageNo) return `\n\n<page-break data-page="${pageNo}" />\n\n`;
      return match; // 保留普通的分隔线
    }
  );
}

// ---------------------------------------------------------------------------
// DocumentViewer 组件
// ---------------------------------------------------------------------------
interface DocumentViewerProps {
  doc: Document;
  scrollToPage?: number | null;
  scrollToHeading?: string | null;
  scrollToImageSrc?: string | null;
  highlightChunks?: ChatSourceChunk[];
  onScrolled?: () => void;
}

export const DocumentViewer = memo(function DocumentViewer({
  doc,
  scrollToPage,
  scrollToHeading,
  scrollToImageSrc,
  highlightChunks,
  onScrolled,
}: DocumentViewerProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const pageCounterRef = useRef(1);
  const [activeHeading, setActiveHeading] = useState<string | null>(null);
  const [showToc, setShowToc] = useState(true);

  // ---- 获取 Markdown 内容 ----
  const { data: markdown, isLoading, error } = useQuery({
    queryKey: ["document-markdown", doc.id],
    queryFn: () => api.getText(`/documents/${doc.id}/markdown`),
    enabled: doc.status === "indexed",
    staleTime: 5 * 60 * 1000, // 缓存 5 分钟
  });

  // ---- 提取标题用于生成目录 ----
  const headings = useMemo(
    () => (markdown ? extractHeadings(markdown) : []),
    [markdown]
  );

  // ---- 处理 Markdown（插入页面分隔线） ----
  const processedMarkdown = useMemo(() => {
    pageCounterRef.current = 1; // 重新处理时重置
    return markdown ? insertPageDividers(markdown) : "";
  }, [markdown]);

  // ---- 稳定的 ReactMarkdown 组件（防止重渲染时重建 DOM） ----
  // 如果不记忆化，内联箭头函数每次渲染都会创建新引用，
  // 导致 React 卸载/重新挂载所有标题元素 —— 破坏高亮类。
  const mdComponents = useMemo<import("react-markdown").Components>(() => ({
    h1: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h1 id={id} {...props}>{children}</h1>;
    },
    h2: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h2 id={id} {...props}>{children}</h2>;
    },
    h3: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h3 id={id} {...props}>{children}</h3>;
    },
    h4: ({ children, ...props }) => {
      const text = getHeadingText(children);
      const id = generateHeadingId(text);
      return <h4 id={id} {...props}>{children}</h4>;
    },
    hr: () => {
      pageCounterRef.current += 1;
      return <PageDivider pageNo={pageCounterRef.current} />;
    },
    p: ({ children, node, ...props }) => {
      const hasImage = (node as any)?.children?.some(
        (child: any) => child.type === "element" && child.tagName === "img"
      );
      if (hasImage)
        return (
          <div className="mb-3 leading-relaxed text-foreground/80" {...props}>
            {children}
          </div>
        );
      return <p {...props}>{children}</p>;
    },
    img: ({ src, alt, ...props }) => (
      <figure className="my-4">
        <img
          src={src}
          alt={alt || ""}
          loading="lazy"
          className="rounded-lg max-w-full mx-auto border border-border/30"
          style={{ minHeight: 120, objectFit: "contain", background: "var(--muted)" }}
          onLoad={(e) => {
            (e.target as HTMLImageElement).style.minHeight = "auto";
            (e.target as HTMLImageElement).style.background = "none";
          }}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
          {...props}
        />
        {alt && (
          <figcaption className="text-xs text-muted-foreground text-center mt-1.5 italic">
            {alt}
          </figcaption>
        )}
      </figure>
    ),
  }), []);

  // 稳定的插件数组
  const remarkPlugins = useMemo(() => [remarkGfm, remarkMath], []);
  const rehypePlugins = useMemo(() => [rehypeKatex], []);

  // ---- 用于跟踪当前活动标题的 IntersectionObserver ----
  useEffect(() => {
    if (!contentRef.current || headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeading(entry.target.id);
          }
        }
      },
      { root: contentRef.current, rootMargin: "-20% 0px -60% 0px", threshold: 0 }
    );

    const headingElements = contentRef.current.querySelectorAll("h1, h2, h3, h4");
    headingElements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [headings, processedMarkdown]);

  // ---- 滚动支持（来自引用交叉链接） ----
  // 手动 scrollTop + rAF 动画 —— 不受浏览器在布局变化
  // （懒加载图片、标签切换等）时取消平滑滚动的影响

  const scrollTo = useCallback(
    (
      target: HTMLElement,
      block: "start" | "center" = "center",
      onDone?: () => void
    ) => {
      const container = contentRef.current;
      if (!container) return;

      const calcTarget = () => {
        // 计算目标元素相对于滚动容器的偏移
        let offset = 0;
        let el: HTMLElement | null = target;
        while (el && el !== container) {
          offset += el.offsetTop;
          el = el.offsetParent as HTMLElement | null;
        }
        const targetH = target.offsetHeight;
        const containerH = container.clientHeight;
        let dest =
          block === "center"
            ? offset - containerH / 2 + targetH / 2
            : offset;
        return Math.max(0, Math.min(dest, container.scrollHeight - containerH));
      };

      // 使用 rAF 动画（与平滑 scrollIntoView 不同，浏览器无法取消）
      const animate = (dest: number) => {
        const start = container.scrollTop;
        const dist = dest - start;
        if (Math.abs(dist) < 1) return;
        const duration = Math.min(400, Math.abs(dist) * 0.5 + 150);
        const t0 = performance.now();
        const step = () => {
          const p = Math.min((performance.now() - t0) / duration, 1);
          const ease = 1 - Math.pow(1 - p, 3); // easeOutCubic 缓动
          container.scrollTop = start + dist * ease;
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      };

      // 执行：先立即滚动，图片加载完成后进行修正
      animate(calcTarget());
      const correctionTimeout = setTimeout(() => {
        animate(calcTarget());
        onDone?.();
      }, 800);
      return () => clearTimeout(correctionTimeout);
    },
    []
  );

  // 用于跟踪上一次滚动操作清理逻辑的 Ref
  const scrollCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    // 清理上一次滚动操作
    scrollCleanupRef.current?.();
    scrollCleanupRef.current = null;

    if (!contentRef.current || !markdown) return;
    if (!scrollToImageSrc && !scrollToHeading && !scrollToPage) return;

    // 双重 rAF：第一次等待 React 提交，第二次等待浏览器绘制。
    // 确保在计算滚动位置前 ReactMarkdown 已完整渲染标题/页面分隔线/图片
    // —— 在标签切换（知识图谱 → 内容）后尤为关键。
    const rafId = requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!contentRef.current) return;

      // 图片引用 —— 滚动到具体图片元素
      if (scrollToImageSrc) {
        const imgEl = contentRef.current.querySelector(
          `img[src="${CSS.escape(scrollToImageSrc)}"]`
        ) as HTMLElement | null;
        if (imgEl) {
          const figure = (imgEl.closest("figure") || imgEl) as HTMLElement;
          scrollCleanupRef.current = scrollTo(figure, "center", onScrolled) ?? null;
          // 在图片容器上闪烁高亮
          figure.classList.add("ring-2", "ring-primary/50", "rounded-lg", "transition-all");
          setTimeout(() => {
            figure.classList.remove("ring-2", "ring-primary/50", "rounded-lg", "transition-all");
          }, 2500);
          return;
        }
        // 回退：滚动到页面
        if (scrollToPage) {
          const pageEl = contentRef.current.querySelector(
            `[data-page="${scrollToPage}"]`
          ) as HTMLElement | null;
          if (pageEl) {
            scrollCleanupRef.current = scrollTo(pageEl, "start", onScrolled) ?? null;
          }
        }
        return;
      }

      if (scrollToHeading) {
        const targetId = generateHeadingId(scrollToHeading);
        const el = contentRef.current.querySelector(
          `#${CSS.escape(targetId)}`
        ) as HTMLElement | null;
        if (el) {
          scrollCleanupRef.current = scrollTo(el, "center", onScrolled) ?? null;
          el.classList.add("bg-primary/20", "transition-colors");
          setTimeout(() => el.classList.remove("bg-primary/20"), 2000);
          return;
        }
      }

      if (scrollToPage) {
        const el = contentRef.current.querySelector(
          `[data-page="${scrollToPage}"]`
        ) as HTMLElement | null;
        if (el) {
          scrollCleanupRef.current = scrollTo(el, "start", onScrolled) ?? null;
        }
      }
    }));

    return () => cancelAnimationFrame(rafId);
  }, [scrollToPage, scrollToHeading, scrollToImageSrc, markdown, onScrolled, scrollTo]);

  // ---- 根据引用高亮分块 ----
  // 依赖 processedMarkdown，以便切换文档后重新应用高亮
  // （Markdown 异步加载 → highlightChunks 首次设置时 DOM 尚未就绪）
  useEffect(() => {
    if (!contentRef.current) return;

    // 始终先清除之前的高亮
    contentRef.current.querySelectorAll(".chunk-hl").forEach((el) => {
      (el as HTMLElement).classList.remove(
        "chunk-hl",
        "chunk-hl-heading",
        "chunk-hl-sibling"
      );
    });

    if (!highlightChunks || highlightChunks.length === 0) return;

    for (const chunk of highlightChunks) {
      // 策略：从 heading_path 找到标题，高亮标题及其同级内容
      const lastHeading =
        chunk.heading_path.length > 0
          ? chunk.heading_path[chunk.heading_path.length - 1]
          : null;

      if (lastHeading) {
        const headingId = generateHeadingId(lastHeading);
        const headingEl = contentRef.current.querySelector(
          `#${CSS.escape(headingId)}`
        );
        if (headingEl) {
          // 高亮标题
          headingEl.classList.add(
            "chunk-hl",
            "chunk-hl-heading"
          );
          // 高亮到下一个标题为止的同级内容
          let sibling = headingEl.nextElementSibling;
          let count = 0;
          while (sibling && !sibling.tagName.match(/^H[1-4]$/) && count < 20) {
            sibling.classList.add(
              "chunk-hl",
              "chunk-hl-sibling"
            );
            sibling = sibling.nextElementSibling;
            count++;
          }
          continue;
        }
      }

    }
    // 滚动由上面的滚动 effect 处理 —— 这里不要争抢
  }, [highlightChunks, processedMarkdown]);

  // ---- 目录标题点击 ----
  const handleTocSelect = useCallback((id: string) => {
    if (!contentRef.current) return;
    const el = contentRef.current.querySelector(`#${CSS.escape(id)}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveHeading(id);
    }
  }, []);

  // ---- 加载 / 错误 / 空状态 ----
  if (doc.status !== "indexed") {
    return <ViewerEmpty />;
  }
  if (isLoading) return <ViewerSkeleton />;
  if (error) return <ViewerError message={(error as Error).message} />;
  if (!markdown || markdown.trim().length === 0) return <ViewerEmpty />;

  return (
    <div className="flex h-full min-h-0">
      {/* 目录侧边栏 */}
      {showToc && (
        <TOCSidebar
          headings={headings}
          activeId={activeHeading}
          onSelect={handleTocSelect}
        />
      )}

      {/* 主要 Markdown 内容 */}
      <div ref={contentRef} className="flex-1 min-h-0 overflow-y-auto">
        {/* 目录开关（用于较小屏幕 / 目录隐藏时） */}
        {headings.length > 0 && (
          <button
            onClick={() => setShowToc(!showToc)}
            className={cn(
              "sticky top-2 left-2 z-10 p-1.5 rounded-md border bg-background/80 backdrop-blur-sm",
              "hover:bg-muted transition-colors 2xl:hidden",
              "flex items-center gap-1 text-xs text-muted-foreground"
            )}
          >
            <List className="w-3.5 h-3.5" />
            <ChevronRight className={cn("w-3 h-3 transition-transform", showToc && "rotate-90")} />
          </button>
        )}

        <div className="px-6 py-4">
          {/* 文档标题头部 */}
          <div className="mb-4 pb-3 border-b">
            <h2 className="text-lg font-semibold">{doc.original_filename}</h2>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
              {doc.page_count && doc.page_count > 0 && <span>{doc.page_count} 页</span>}
              {doc.chunk_count > 0 && <span>{doc.chunk_count} 分块</span>}
              {doc.parser_version && <span>由 {doc.parser_version} 解析</span>}
            </div>
          </div>

          {/* 渲染后的 Markdown */}
          <article
            className={cn(
              "prose prose-sm max-w-none text-foreground/80",
              // 标题 —— 显式设置前景色，以支持浅色/深色主题
              "[&_h1]:text-xl [&_h1]:font-bold [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:scroll-mt-4 [&_h1]:text-foreground",
              "[&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:scroll-mt-4 [&_h2]:text-foreground",
              "[&_h3]:text-base [&_h3]:font-semibold [&_h3]:mt-4 [&_h3]:mb-2 [&_h3]:scroll-mt-4 [&_h3]:text-foreground",
              "[&_h4]:text-sm [&_h4]:font-semibold [&_h4]:mt-3 [&_h4]:mb-1.5 [&_h4]:scroll-mt-4 [&_h4]:text-foreground",
              // 正文文本
              "[&_p]:text-foreground/80 [&_p]:leading-relaxed [&_p]:mb-3",
              "[&_li]:text-foreground/80",
              "[&_strong]:text-foreground",
              // 表格
              "[&_table]:w-full [&_table]:border-collapse [&_table]:text-xs",
              "[&_th]:bg-muted/50 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_th]:text-foreground/80",
              "[&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1.5 [&_td]:text-foreground/80",
              // 代码
              "[&_code]:bg-muted/50 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-xs [&_code]:text-foreground/90",
              "[&_pre]:bg-muted/30 [&_pre]:rounded-lg [&_pre]:p-3 [&_pre]:overflow-x-auto [&_pre]:text-xs",
              // 引用块
              "[&_blockquote]:border-l-2 [&_blockquote]:border-primary/30 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-foreground/60",
              // 图片
              "[&_img]:rounded-lg [&_img]:max-w-full [&_img]:my-3",
              // 链接
              "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
              // KaTeX 公式块
              "[&_.katex-display]:overflow-x-auto [&_.katex-display]:py-2",
              "[&_.katex]:text-[0.95em]"
            )}
          >
            <ReactMarkdown
              remarkPlugins={remarkPlugins}
              rehypePlugins={rehypePlugins}
              components={mdComponents}
            >
              {processedMarkdown}
            </ReactMarkdown>
          </article>
        </div>
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// 辅助函数
// ---------------------------------------------------------------------------
function getHeadingText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(getHeadingText).join("");
  if (children && typeof children === "object" && "props" in children) {
    return getHeadingText((children as React.ReactElement<{ children?: React.ReactNode }>).props.children);
  }
  return String(children ?? "");
}

function generateHeadingId(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 80);
}
