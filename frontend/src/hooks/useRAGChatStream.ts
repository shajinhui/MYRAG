/**
 * useRAGChatStream —— 用于 MYRAG 聊天的 SSE 流式 Hook。
 *
 * 处理来自 /chat/{workspace_id}/stream 接口的 Server-Sent Events，
 * 包含 rAF 缓冲令牌渲染、AgentStep 跟踪以及 AbortController 清理。
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { generateId } from "@/lib/utils";
import type {
  ChatSourceChunk,
  ChatImageRef,
  ChatStreamStatus,
  ChatMessage,
  AgentStep,
  AgentStepType,
} from "@/types";
import { BASE_URL } from "@/lib/api";

export interface RAGStreamResult {
  /** 当前流状态 */
  status: ChatStreamStatus;
  /** 累计的流式内容（到目前为止的答案文本） */
  streamingContent: string;
  /** 累计的思考文本 */
  thinkingText: string;
  /** 从检索接收到的来源 */
  pendingSources: ChatSourceChunk[];
  /** 从检索接收到的图片引用 */
  pendingImages: ChatImageRef[];
  /** 错误信息（如果有） */
  error: string | null;
  /** 当前是否正在流式输出 */
  isStreaming: boolean;
  /** 供 ThinkingTimeline 使用的智能体处理步骤 */
  agentSteps: AgentStep[];
  /** 发送消息 —— 完成时返回最终化的 ChatMessage */
  sendMessage: (
    message: string,
    history: { role: string; content: string }[],
    enableThinking: boolean,
    forceSearch?: boolean,
  ) => Promise<ChatMessage | null>;
  /** 取消正在进行的流 */
  cancel: () => void;
  /** 重置所有状态 */
  reset: () => void;
}

// ---------------------------------------------------------------------------
// AgentStep 辅助函数
// ---------------------------------------------------------------------------

function createStep(
  step: AgentStepType,
  detail: string,
  status: "active" | "completed" | "error" = "active",
): AgentStep {
  return {
    id: generateId(),
    step,
    detail,
    status,
    timestamp: Date.now(),
  };
}

function completeActiveStep(steps: AgentStep[]): AgentStep[] {
  const now = Date.now();
  return steps.map((s) =>
    s.status === "active"
      ? { ...s, status: "completed" as const, durationMs: now - s.timestamp }
      : s,
  );
}

function markActiveError(steps: AgentStep[]): AgentStep[] {
  return steps.map((s) =>
    s.status === "active" ? { ...s, status: "error" as const } : s,
  );
}

// ---------------------------------------------------------------------------
// Hook 本体
// ---------------------------------------------------------------------------

export function useRAGChatStream(workspaceId: string): RAGStreamResult {
  const [status, setStatus] = useState<ChatStreamStatus>("idle");
  const [streamingContent, setStreamingContent] = useState("");
  const [thinkingText, setThinkingText] = useState("");
  const [pendingSources, setPendingSources] = useState<ChatSourceChunk[]>([]);
  const [pendingImages, setPendingImages] = useState<ChatImageRef[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const bufferRef = useRef("");
  const rafRef = useRef<number | undefined>(undefined);

  // 独立的思考文本缓冲区，用于 AgentStep 的 thinkingText 更新
  const thinkingBufferRef = useRef("");
  const thinkingRafRef = useRef<number | undefined>(undefined);

  // 记录开始时间，用于计算总耗时
  const streamStartRef = useRef(0);

  // 卸载时清理 —— 中止请求、取消读取器并清除待处理的 RAF
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      readerRef.current?.cancel().catch(() => {});
      readerRef.current = null;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (thinkingRafRef.current) cancelAnimationFrame(thinkingRafRef.current);
    };
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setStreamingContent("");
    setThinkingText("");
    setPendingSources([]);
    setPendingImages([]);
    setError(null);
    setIsStreaming(false);
    setAgentSteps([]);
    bufferRef.current = "";
    thinkingBufferRef.current = "";
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = undefined;
    }
    if (thinkingRafRef.current) {
      cancelAnimationFrame(thinkingRafRef.current);
      thinkingRafRef.current = undefined;
    }
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    readerRef.current?.cancel().catch(() => {});
    readerRef.current = null;
    setStatus("idle");
    setIsStreaming(false);
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = undefined;
    }
    if (thinkingRafRef.current) {
      cancelAnimationFrame(thinkingRafRef.current);
      thinkingRafRef.current = undefined;
    }
    // 刷新剩余的令牌缓冲区
    if (bufferRef.current) {
      const remaining = bufferRef.current;
      bufferRef.current = "";
      setStreamingContent((prev) => prev + remaining);
    }
  }, []);

  const onToken = useCallback((text: string) => {
    bufferRef.current += text;
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        const chunk = bufferRef.current;
        bufferRef.current = "";
        rafRef.current = undefined;
        setStreamingContent((prev) => prev + chunk);
      });
    }
  }, []);

  // 为 analyzing AgentStep 进行缓冲的思考文本更新
  const onThinkingToken = useCallback((text: string) => {
    // 更新扁平化的 thinkingText 状态（保持原有行为）
    setThinkingText((prev) => prev + text);

    // 缓冲思考文本，用于 AgentStep 更新
    thinkingBufferRef.current += text;
    if (!thinkingRafRef.current) {
      thinkingRafRef.current = requestAnimationFrame(() => {
        const chunk = thinkingBufferRef.current;
        thinkingBufferRef.current = "";
        thinkingRafRef.current = undefined;

        setAgentSteps((prev) => {
          // 无论状态如何都查找 analyzing 步骤 —— 思考文本可能在
          // 第一次迭代（analyzing=active）和工具调用后的
          // 第二次迭代（analyzing=completed）期间到达。
          const idx = prev.findIndex((s) => s.step === "analyzing");
          if (idx === -1) return prev;
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            thinkingText: (updated[idx].thinkingText || "") + chunk,
          };
          return updated;
        });
      });
    }
  }, []);

  const sendMessage = useCallback(
    async (
      message: string,
      history: { role: string; content: string }[],
      enableThinking: boolean,
      forceSearch: boolean = false,
    ): Promise<ChatMessage | null> => {
      // 在发起新请求前中止正在进行的请求
      abortRef.current?.abort();
      readerRef.current?.cancel().catch(() => {});
      readerRef.current = null;

      // 取消上一个流遗留的 RAF
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = undefined;
      }
      if (thinkingRafRef.current) {
        cancelAnimationFrame(thinkingRafRef.current);
        thinkingRafRef.current = undefined;
      }

      // 为新消息重置状态
      setStreamingContent("");
      setThinkingText("");
      setPendingSources([]);
      setPendingImages([]);
      setError(null);
      setStatus("analyzing");
      setIsStreaming(true);
      setAgentSteps([]);
      bufferRef.current = "";
      thinkingBufferRef.current = "";
      streamStartRef.current = Date.now();

      // 同步的本地跟踪器 —— 避免 React 18 批处理竞态条件，
      // 即 sendMessage 完成时 ChatPanel 中的 agentStepsRef 可能已过期
      let localSteps: AgentStep[] = [];
      // 在此作用域内累计所有思考文本，以便完成时刷新到
      // localSteps（onThinkingToken 只通过 RAF 更新 setAgentSteps，
      // 不会同步回 localSteps）
      let thinkingAccumulator = "";
      function syncUpdateSteps(updater: AgentStep[] | ((prev: AgentStep[]) => AgentStep[])): void {
        const next = typeof updater === "function" ? updater(localSteps) : updater;
        localSteps = next;
        setAgentSteps(next);
      }

      abortRef.current = new AbortController();

      try {
        const response = await fetch(
          `${BASE_URL}/rag/chat/${workspaceId}/stream`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              message,
              history,
              enable_thinking: enableThinking,
              force_search: forceSearch,
            }),
            signal: abortRef.current.signal,
          },
        );

        if (!response.ok) {
          const err = await response
            .json()
            .catch(() => ({ detail: "流式请求失败" }));
          throw new Error(err.detail || `错误：${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("无响应内容");
        readerRef.current = reader;

        const decoder = new TextDecoder();
        let sseBuffer = "";
        let currentEventType = "unknown";
        let finalMessage: ChatMessage | null = null;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          sseBuffer += decoder.decode(value, { stream: true });
          const lines = sseBuffer.split("\n");
          sseBuffer = lines.pop() || "";

          for (const line of lines) {
            // 跳过心跳注释行
            if (line.startsWith(":")) continue;

            if (line.startsWith("event: ")) {
              currentEventType = line.slice(7).trim();
              continue;
            }

            if (line.startsWith("data: ")) {
              const jsonStr = line.slice(6).trim();
              if (!jsonStr) continue;

              try {
                const data = JSON.parse(jsonStr);

                switch (currentEventType) {
                  case "status": {
                    const step = data.step as string;
                    const detail = (data.detail as string) || "";

                    if (step === "analyzing") {
                      setStatus("analyzing");
                      syncUpdateSteps((prev) => [
                        ...prev,
                        createStep("analyzing", detail || "正在分析你的问题..."),
                      ]);
                    } else if (step === "retrieving") {
                      setStatus("retrieving");
                      syncUpdateSteps((prev) => [
                        ...completeActiveStep(prev),
                        createStep("understood", "已理解查询", "completed"),
                        createStep("retrieving", detail || "正在搜索文档..."),
                      ]);
                    } else if (step === "generating") {
                      setStatus("generating");
                      syncUpdateSteps((prev) => [
                        ...completeActiveStep(prev),
                        createStep("generating", detail || "正在生成回答..."),
                      ]);
                    }
                    break;
                  }

                  case "thinking":
                    onThinkingToken(data.text || "");
                    thinkingAccumulator += data.text || "";
                    break;

                  case "sources": {
                    const sources = (data.sources || []) as ChatSourceChunk[];
                    setPendingSources((prev) => [...prev, ...sources]);

                    // 添加带徽章的 sources_found 步骤
                    const badges = sources.map((s) => String(s.index));
                    syncUpdateSteps((prev) => [
                      ...completeActiveStep(prev),
                      createStep("sources_found", `找到 ${sources.length} 个来源`, "completed"),
                    ].map((s) =>
                      s.step === "sources_found" && s.status === "completed" && !s.sourceBadges
                        ? { ...s, sourceBadges: badges, sourceCount: sources.length }
                        : s,
                    ));
                    break;
                  }

                  case "images": {
                    const imgs = (data.image_refs || []) as ChatImageRef[];
                    setPendingImages((prev) => [...prev, ...imgs]);

                    // 用图片数量更新 sources_found 步骤
                    if (imgs.length > 0) {
                      syncUpdateSteps((prev) => {
                        let lastSourcesIdx = -1;
                        for (let i = prev.length - 1; i >= 0; i--) {
                          if (prev[i].step === "sources_found") {
                            lastSourcesIdx = i;
                            break;
                          }
                        }
                        if (lastSourcesIdx === -1) return prev;
                        const updated = [...prev];
                        const existing = updated[lastSourcesIdx];
                        updated[lastSourcesIdx] = {
                          ...existing,
                          imageCount: (existing.imageCount || 0) + imgs.length,
                          detail: `找到 ${existing.sourceCount || 0} 个来源和 ${(existing.imageCount || 0) + imgs.length} 张图片`,
                        };
                        return updated;
                      });
                    }
                    break;
                  }

                  case "token":
                    onToken(data.text || "");
                    break;

                  case "token_rollback":
                    // 清除推测性令牌
                    bufferRef.current = "";
                    if (rafRef.current) {
                      cancelAnimationFrame(rafRef.current);
                      rafRef.current = undefined;
                    }
                    setStreamingContent("");
                    break;

                  case "complete": {
                    // 刷新剩余缓冲区
                    if (bufferRef.current) {
                      bufferRef.current = "";
                      if (rafRef.current) {
                        cancelAnimationFrame(rafRef.current);
                        rafRef.current = undefined;
                      }
                    }
                    // 将累计的思考文本刷新到 localSteps，
                    // 使 finalMessage.agentSteps 包含 thinkingText
                    if (thinkingAccumulator) {
                      syncUpdateSteps((prev) =>
                        prev.map((s) =>
                          s.step === "analyzing"
                            ? { ...s, thinkingText: (s.thinkingText || "") + thinkingAccumulator }
                            : s,
                        ),
                      );
                      thinkingAccumulator = "";
                    }
                    // 刷新思考缓冲区（取消待处理的 RAF）
                    if (thinkingBufferRef.current) {
                      thinkingBufferRef.current = "";
                      if (thinkingRafRef.current) {
                        cancelAnimationFrame(thinkingRafRef.current);
                        thinkingRafRef.current = undefined;
                      }
                    }

                    // 完成激活步骤并添加 done 步骤（同时同步 localSteps）
                    const totalMs = Date.now() - streamStartRef.current;
                    syncUpdateSteps((prev) => [
                      ...completeActiveStep(prev),
                      createStep("done", `耗时 ${totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}`, "completed"),
                    ]);

                    finalMessage = {
                      id: generateId(),
                      role: "assistant",
                      content: data.answer || "",
                      sources: data.sources || [],
                      relatedEntities: data.related_entities || [],
                      imageRefs: data.image_refs || [],
                      thinking: data.thinking || null,
                      agentSteps: localSteps, // 将同步后的步骤直接包含在 finalMessage 中
                      timestamp: new Date().toISOString(),
                    };
                    break;
                  }

                  case "error":
                    setError(data.message || "未知错误");
                    setStatus("error");
                    syncUpdateSteps((prev) => markActiveError(prev));
                    break;
                }
              } catch {
                // 忽略格式错误的 JSON
              }
            }
          }
        }

        readerRef.current = null;
        setStatus("idle");
        setIsStreaming(false);

        return finalMessage;
      } catch (err) {
        readerRef.current = null;
        if ((err as Error).name === "AbortError") {
          // 用户取消了 —— 不设置错误
          return null;
        }
        const msg = (err as Error).message || "流式请求失败";
        setError(msg);
        setStatus("error");
        setIsStreaming(false);
        syncUpdateSteps((prev) => markActiveError(prev));
        return null;
      }
    },
    [workspaceId, onToken, onThinkingToken],
  );

  return {
    status,
    streamingContent,
    thinkingText,
    pendingSources,
    pendingImages,
    error,
    isStreaming,
    agentSteps,
    sendMessage,
    cancel,
    reset,
  };
}
