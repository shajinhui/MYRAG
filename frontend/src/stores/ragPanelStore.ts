/**
 * RAG 面板 Store
 * ===============
 *
 * 使用 Zustand 管理文档详情面板状态。
 * 控制显示哪个面板（查看器 / 图库 / 引用）、选中的文档以及面板宽度。
 */

import { create } from "zustand";
import type { Document, Citation } from "@/types";

export type PanelView = "viewer" | "gallery" | null;

interface RagPanelState {
  /** 当前激活的面板视图 */
  activePanel: PanelView;

  /** 当前在面板中显示的文档 */
  selectedDoc: Document | null;

  /** 可选：从引用打开时滚动到的目标 */
  scrollToPage: number | null;
  scrollToHeading: string | null;

  /** 以指定视图和文档打开面板 */
  openPanel: (view: PanelView, doc: Document) => void;

  /** 切换视图但不更换文档 */
  setView: (view: PanelView) => void;

  /** 关闭面板 */
  closePanel: () => void;

  /** 在指定引用位置打开查看器 */
  openAtCitation: (doc: Document, citation: Citation) => void;

  /** 导航后清除滚动目标 */
  clearScrollTarget: () => void;
}

export const useRagPanelStore = create<RagPanelState>((set) => ({
  activePanel: null,
  selectedDoc: null,
  scrollToPage: null,
  scrollToHeading: null,

  openPanel: (view, doc) =>
    set({
      activePanel: view,
      selectedDoc: doc,
      scrollToPage: null,
      scrollToHeading: null,
    }),

  setView: (view) => set({ activePanel: view }),

  closePanel: () =>
    set({
      activePanel: null,
      selectedDoc: null,
      scrollToPage: null,
      scrollToHeading: null,
    }),

  openAtCitation: (doc, citation) =>
    set({
      activePanel: "viewer",
      selectedDoc: doc,
      scrollToPage: citation.page_no,
      scrollToHeading: citation.heading_path.length > 0
        ? citation.heading_path[citation.heading_path.length - 1]
        : null,
    }),

  clearScrollTarget: () =>
    set({ scrollToPage: null, scrollToHeading: null }),
}));
