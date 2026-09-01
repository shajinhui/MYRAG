export const ENTITY_TYPE_LABELS: Record<string, string> = {
  person: "人物",
  organization: "组织",
  product: "产品",
  location: "地点",
  event: "事件",
  concept: "概念",
  financial_metric: "财务指标",
  technology: "技术",
  date: "日期",
  regulation: "法规",
};

export function entityTypeLabel(type: string): string {
  return ENTITY_TYPE_LABELS[type.toLowerCase()] ?? type;
}
