/**
 * 工作区 Store
 * ===============
 * 使用 Zustand 管理三栏工作区布局。
 * 管理：文档选择、可视化面板标签、引用高亮。
 *
 * 滚动策略分为两个阶段：
 *   阶段 1：打开内容视图（selectDoc + activeTab），清除滚动目标
 *   阶段 2：内容稳定后设置滚动目标（触发滚动效果）
 *   同一文档内容已可见时，直接跳到阶段 2（立即滚动）。
 */

import { create } from "zustand";
import type { Document, ChatSourceChunk, ChatImageRef } from "@/types";

export type VisualTab = "content" | "kg";
export type KGSubTab = "graph" | "entities";

// 模块级定时器，用于取消过期的延迟滚动
let _scrollTimer: ReturnType<typeof setTimeout> | null = null;

/** 应用滚动目标前等待内容渲染完成的时间（毫秒） */
const SCROLL_DEFER_MS = 350;

interface WorkspaceState {
  // 文档选择
  selectedDoc: Document | null;

  // 可视化面板标签
  activeTab: VisualTab;
  kgSubTab: KGSubTab;

  // 滚动目标（用于引用 → 内容导航）
  scrollToPage: number | null;
  scrollToHeading: string | null;
  scrollToImageSrc: string | null;

  // 引用高亮
  highlightChunks: ChatSourceChunk[];
  highlightEntities: string[];
  activeCitationIndex: number | string | null;

  // 操作
  selectDoc: (doc: Document | null) => void;
  setActiveTab: (tab: VisualTab) => void;
  setKgSubTab: (tab: KGSubTab) => void;
  activateCitation: (source: ChatSourceChunk, allEntities: string[], doc?: Document) => void;
  activateCitationKG: (source: ChatSourceChunk, allEntities: string[], doc?: Document) => void;
  activateImageCitation: (imageRef: ChatImageRef, doc?: Document) => void;
  clearHighlights: () => void;
  clearScrollTarget: () => void;
  /** 重置所有状态 —— 当 workspaceId 变化时调用 */
  reset: () => void;
}

function cancelPendingScroll() {
  if (_scrollTimer) {
    clearTimeout(_scrollTimer);
    _scrollTimer = null;
  }
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  selectedDoc: null,
  activeTab: "content",
  kgSubTab: "graph",
  scrollToPage: null,
  scrollToHeading: null,
  scrollToImageSrc: null,
  highlightChunks: [],
  highlightEntities: [],
  activeCitationIndex: null,

  selectDoc: (doc) => {
    cancelPendingScroll();
    set({
      selectedDoc: doc,
      activeTab: "content",
      highlightChunks: [],
      highlightEntities: [],
      activeCitationIndex: null,
      scrollToPage: null,
      scrollToHeading: null,
      scrollToImageSrc: null,
    });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),
  setKgSubTab: (tab) => set({ kgSubTab: tab }),

  activateCitation: (source, allEntities, doc) => {
    cancelPendingScroll();

    const state = get();
    const contentAlreadyOpen =
      state.activeTab === "content" &&
      state.selectedDoc != null &&
      (!doc || state.selectedDoc.id === doc.id);

    const scrollTargets = {
      scrollToPage: source.page_no || null,
      scrollToHeading:
        source.heading_path.length > 0
          ? source.heading_path[source.heading_path.length - 1]
          : null,
      scrollToImageSrc: null as string | null,
    };

    // 阶段 1：打开内容并设置高亮（始终执行）
    set({
      ...(doc ? { selectedDoc: doc } : {}),
      highlightChunks: [source],
      highlightEntities: allEntities,
      activeCitationIndex: source.index,
      activeTab: "content",
      // 内容已打开则立即滚动，否则清除并延迟
      ...(contentAlreadyOpen
        ? scrollTargets
        : { scrollToPage: null, scrollToHeading: null, scrollToImageSrc: null }),
    });

    // 阶段 2：内容渲染完成后延迟滚动
    if (!contentAlreadyOpen) {
      _scrollTimer = setTimeout(() => {
        _scrollTimer = null;
        set(scrollTargets);
      }, SCROLL_DEFER_MS);
    }
  },

  activateCitationKG: (source, allEntities, doc) => {
    cancelPendingScroll();
    set({
      ...(doc ? { selectedDoc: doc } : {}),
      highlightChunks: [source],
      highlightEntities: allEntities,
      activeCitationIndex: source.index,
      activeTab: "kg",
      kgSubTab: "graph",
    });
  },

  activateImageCitation: (imageRef, doc) => {
    cancelPendingScroll();

    const state = get();
    const contentAlreadyOpen =
      state.activeTab === "content" &&
      state.selectedDoc != null &&
      (!doc || state.selectedDoc.id === doc.id);

    const scrollTargets = {
      scrollToPage: imageRef.page_no || null,
      scrollToImageSrc: imageRef.url,
      scrollToHeading: null as string | null,
    };

    set({
      ...(doc ? { selectedDoc: doc } : {}),
      activeTab: "content",
      highlightChunks: [],
      highlightEntities: [],
      activeCitationIndex: null,
      ...(contentAlreadyOpen
        ? scrollTargets
        : { scrollToPage: null, scrollToHeading: null, scrollToImageSrc: null }),
    });

    if (!contentAlreadyOpen) {
      _scrollTimer = setTimeout(() => {
        _scrollTimer = null;
        set(scrollTargets);
      }, SCROLL_DEFER_MS);
    }
  },

  clearHighlights: () =>
    set({
      highlightChunks: [],
      highlightEntities: [],
      activeCitationIndex: null,
    }),

  clearScrollTarget: () =>
    set({ scrollToPage: null, scrollToHeading: null, scrollToImageSrc: null }),

  reset: () => {
    cancelPendingScroll();
    set({
      selectedDoc: null,
      activeTab: "content",
      kgSubTab: "graph",
      scrollToPage: null,
      scrollToHeading: null,
      scrollToImageSrc: null,
      highlightChunks: [],
      highlightEntities: [],
      activeCitationIndex: null,
    });
  },
}));
