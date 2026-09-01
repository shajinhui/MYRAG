/**
 * MemoizedMarkdown —— 高效的流式 Markdown 渲染器。
 *
 * 将内容拆分为段落块，并对已完成块进行记忆化，
 * 使每次令牌更新时只有进行中（最后一个）的块重新渲染。
 *
 * 通过清洗进行中的内容，处理不完整的 LaTeX（$$）、代码围栏（```）
 * 和表格，避免渲染错误。
 */
import { memo, useMemo } from "react";
import type { ChatSourceChunk, ChatImageRef } from "@/types";

// ---------------------------------------------------------------------------
// 块拆分 —— 将内容分为已完成块和进行中块
// ---------------------------------------------------------------------------

interface SplitResult {
  completed: string[];
  inProgress: string;
}

/**
 * 将 Markdown 内容拆分为段落块（按空行分隔）。
 * 跟踪未闭合的代码围栏和 LaTeX 块，避免在它们内部拆分。
 */
export function splitIntoBlocks(content: string): SplitResult {
  const lines = content.split("\n");
  const blocks: string[] = [];
  let currentBlock: string[] = [];
  let inCodeFence = false;
  let inLatexBlock = false;

  for (const line of lines) {
    // 跟踪代码围栏状态
    if (line.trimStart().startsWith("```")) {
      inCodeFence = !inCodeFence;
    }

    // 跟踪 $$ LaTeX 块状态（仅当不在代码围栏内时）
    if (!inCodeFence) {
      const trimmed = line.trim();
      // 匹配以 $$ 开头（打开/关闭显示公式）的行
      if (trimmed === "$$" || (trimmed.startsWith("$$") && !trimmed.endsWith("$$"))) {
        inLatexBlock = !inLatexBlock;
      } else if (trimmed.endsWith("$$") && inLatexBlock) {
        inLatexBlock = false;
      }
    }

    // 空行 = 段落边界（仅当不在围栏/LaTeX 块内时）
    if (line.trim() === "" && !inCodeFence && !inLatexBlock) {
      if (currentBlock.length > 0) {
        blocks.push(currentBlock.join("\n"));
        currentBlock = [];
      }
      continue;
    }

    currentBlock.push(line);
  }

  // 如果处于未闭合的围栏/LaTeX 块内，最后一块视为进行中
  if (inCodeFence || inLatexBlock || currentBlock.length > 0) {
    const inProgress = currentBlock.join("\n");
    return { completed: blocks, inProgress };
  }

  // 所有块已完成（内容以空行结束或为空）
  return { completed: blocks, inProgress: "" };
}

// ---------------------------------------------------------------------------
// 清洗进行中的文本 —— 移除不完整的结构
// ---------------------------------------------------------------------------

/**
 * 从进行中的文本中移除不完整的 $$ 块、``` 围栏和表格行，
 * 防止渲染出错。
 */
export function sanitizeInProgress(text: string): string {
  if (!text) return "";

  let result = text;

  // 自动闭合不完整的 $$ 块，使 KaTeX 可以渲染部分公式。
  const latexCount = (result.match(/\$\$/g) || []).length;
  if (latexCount % 2 !== 0) {
    const lastIdx = result.lastIndexOf("$$");
    const afterDollars = result.slice(lastIdx + 2);
    if (afterDollars.trim()) {
      result = result.slice(0, lastIdx) + "$$\n" + afterDollars.trimStart() + "\n$$";
    } else {
      result = result + "\n$$";
    }
  }

  // 自动闭合不完整的 ``` 块，使代码带高亮渲染
  const fenceCount = (result.match(/```/g) || []).length;
  if (fenceCount % 2 !== 0) {
    result = result + "\n```";
  }

  // 移除不完整的表格行（以 | 开头但未以 | 结尾）
  const lines = result.split("\n");
  while (lines.length > 0) {
    const last = lines[lines.length - 1];
    if (last.startsWith("|") && !last.trimEnd().endsWith("|")) {
      lines.pop();
    } else {
      break;
    }
  }
  result = lines.join("\n");

  return result.trimEnd();
}

// ---------------------------------------------------------------------------
// 用于稳定键的简单快速哈希
// ---------------------------------------------------------------------------
function stableHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i);
    hash = ((hash << 5) - hash + ch) | 0;
  }
  return hash.toString(36);
}

// ---------------------------------------------------------------------------
// 记忆化的单个块 —— 通过传入的渲染函数渲染
// ---------------------------------------------------------------------------

interface MemoizedBlockProps {
  content: string;
  renderFn: (content: string) => React.ReactNode;
}

const MemoizedMarkdownBlock = memo(
  function MemoizedMarkdownBlock({ content, renderFn }: MemoizedBlockProps) {
    return <>{renderFn(content)}</>;
  },
  (prev, next) => prev.content === next.content && prev.renderFn === next.renderFn
);

// ---------------------------------------------------------------------------
// StreamingMarkdown —— 主导出
// ---------------------------------------------------------------------------

export interface StreamingMarkdownProps {
  content: string;
  sources?: ChatSourceChunk[];
  imageRefs?: ChatImageRef[];
  isStreaming?: boolean;
  /** 单个 Markdown 块的渲染函数（使用 MarkdownWithCitations） */
  renderBlock: (content: string) => React.ReactNode;
}

/**
 * 支持流式的 Markdown 渲染器。
 *
 * 已完成的段落块会被记忆化（永不重新渲染）。
 * 只有进行中的块会在每个令牌更新时重新渲染。
 */
export function StreamingMarkdown({
  content,
  isStreaming = false,
  renderBlock,
}: StreamingMarkdownProps) {
  const { completed, inProgress } = useMemo(
    () => splitIntoBlocks(content),
    [content]
  );

  const sanitized = useMemo(
    () => (isStreaming ? sanitizeInProgress(inProgress) : inProgress),
    [inProgress, isStreaming]
  );

  return (
    <>
      {/* 已完成的块 —— 完全记忆化，永不重新渲染 */}
      {completed.map((block, i) => (
        <MemoizedMarkdownBlock
          key={`b-${stableHash(block)}-${i}`}
          content={block}
          renderFn={renderBlock}
        />
      ))}

      {/* 进行中的块 —— 每个令牌更新时重新渲染（父组件遮罩处理淡出） */}
      {sanitized ? renderBlock(sanitized) : null}
    </>
  );
}
