// SPDX-License-Identifier: AGPL-3.0-only
export type OwnerMetric = { key: string; label: string };
export type OwnerGroup = {
  owner_id: string;
  name: string;
  active: boolean;
  count: number;
  statuses?: { status: string; count: number }[];
};
export type OwnerRecord = {
  id: string;
  title: string;
  url: string;
  project_id: string;
  project_name: string;
  status: string;
  kind: string;
};
export type OwnerSelection = { owner_id: string; status?: string };
const uiKeys = [
  "page",
  "per_page",
  "tab",
  "panel",
  "layout",
  "saved_view",
  "defect",
  "case",
  "plan",
  "create",
  "owner_scope",
  "owner_metric",
  "owner_page",
  "owner_id",
  "owner_status",
  "owner_name",
  "owner_detail_page",
  "return_to",
];
export function ownerStatisticsQuery(
  params: URLSearchParams,
  source: string,
  metric: string,
  page: number,
  selected?: OwnerSelection
) {
  const query = new URLSearchParams(params);
  for (const key of uiKeys) query.delete(key);
  for (const key of [...query.keys()].filter((name) => name.startsWith("report_"))) query.delete(key);
  query.set("source", source);
  query.set("metric", metric);
  query.set("page", String(page));
  query.set("per_page", selected ? "20" : "10");
  if (selected) {
    query.set("owner_id", selected.owner_id);
    if (selected.status) query.set("owner_status", selected.status);
  }
  return query;
}
export const ownerStatusNames: Record<string, string> = {
  open: "待处理",
  pending_tech: "待技术确认",
  needs_tech: "待技术处理",
  in_progress: "处理中",
  resolved: "待回归",
  closed: "已关闭",
  backlog: "待排期",
  unstarted: "未开始",
  started: "处理中",
  completed: "已完成",
  cancelled: "已取消",
  pending: "待执行",
  ready: "待开始",
  running: "执行中",
  paused: "已暂停",
  review: "待确认",
  returned: "待复测",
  returned_test: "退回补测",
  returned_repair: "退回修复",
  reopened: "已重开",
  superseded: "已调整",
  passed: "通过",
  failed: "失败",
  blocked: "阻塞",
  inconclusive: "无法判定",
  skipped: "跳过",
  active: "有效",
  inactive: "停用",
  planned: "计划中",
  "in-progress": "进行中",
  high: "高",
  medium: "中",
  low: "低",
  urgent: "紧急",
  none: "未设置",
  critical: "紧急",
  major: "高",
  minor: "中",
  trivial: "低",
  "5": "访客",
  "15": "成员",
  "20": "工作空间管理成员",
  accepted: "已验收",
  draft: "草稿",
  published: "已发布",
  unexecuted: "待执行",
};
export const ownerStatusColors: Record<string, string> = {
  open: "text-warning-primary",
  pending_tech: "text-warning-primary",
  needs_tech: "text-danger-primary",
  in_progress: "text-accent-primary",
  resolved: "text-warning-primary",
  closed: "text-success-primary",
  started: "text-accent-primary",
  completed: "text-success-primary",
  running: "text-accent-primary",
  returned: "text-danger-primary",
  failed: "text-danger-primary",
  blocked: "text-danger-primary",
  passed: "text-success-primary",
  accepted: "text-success-primary",
  inconclusive: "text-warning-primary",
};
export function ownerRecordHref(url: string, returnTo: string) {
  if (!url.startsWith("/") || url.startsWith("//")) return "";
  const next = new URL(url, "https://local.invalid");
  next.searchParams.set("return_to", returnTo);
  return `${next.pathname}${next.search}${next.hash}`;
}

export const ownerKindNames: Record<string, string> = {
  work: "任务与需求",
  task: "任务",
  requirement: "需求",
  defect: "缺陷",
  plan: "测试计划",
  case: "用例",
  item: "本轮用例",
  execution: "执行记录",
  verification_case: "缺陷回归用例",
  case_execution: "缺陷用例执行",
  verification: "验证轮次",
  manual_execution: "人工验证",
  project: "项目",
  cycle: "周期",
  module: "模块",
  page: "文档",
  view: "视图",
  member: "成员",
};

export function ownerStatisticsScope(endpoint: string, source: string, params: URLSearchParams) {
  const query = ownerStatisticsQuery(params, source, "", 1);
  query.delete("metric");
  query.delete("page");
  query.delete("per_page");
  query.sort();
  return JSON.stringify([endpoint, source, query.toString()]);
}
