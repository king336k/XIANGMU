import type { TWorkItemFilterExpression } from "@plane/types";

export const profileStateLabels: Record<string, string> = {
  backlog: "待排期",
  unstarted: "待开始",
  started: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};
export const profilePriorityLabels: Record<string, string> = {
  urgent: "紧急",
  high: "高",
  medium: "中",
  low: "低",
  none: "未设置",
};
export function profileWorkItemsHref(
  workspace: string,
  user: string,
  view = "assigned",
  filters: Record<string, string | undefined> = {}
) {
  const query = new URLSearchParams({ from: "summary" });
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined) query.set(key, value);
  }
  return `/${workspace}/profile/${user}/${view}/?${query}`;
}
// 统计入口不沿用旧筛选，确保列表范围与卡片数量一致。
export function profileSummaryFilters(query: URLSearchParams): TWorkItemFilterExpression | undefined {
  if (query.get("from") !== "summary") return undefined;
  const filters: TWorkItemFilterExpression = {};
  const group = query.get("state_group"),
    priority = query.get("priority"),
    project = query.get("project_id");
  if (group && Object.hasOwn(profileStateLabels, group)) filters.state_group__in = group;
  if (priority && Object.hasOwn(profilePriorityLabels, priority)) filters.priority__in = priority;
  if (project && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(project))
    filters.project_id__in = project;
  if (query.get("pending") === "1") filters.state_group__in = "backlog,unstarted,started";
  return filters;
}
