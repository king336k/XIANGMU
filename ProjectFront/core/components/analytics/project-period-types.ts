// SPDX-License-Identifier: AGPL-3.0-only
export type Workload = {
  user_id: string;
  name: string;
  role: string;
  work: Record<string, number>;
  plans: Record<string, number>;
  defects: Record<string, number>;
  period_executions: number;
};
export type ProjectReport = {
  project: { id: string; name: string };
  start: string;
  end: string;
  timezone: string;
  activity: Record<string, number>;
  current: Record<string, number>;
  test_results: Record<string, number>;
  manual_results?: Record<string, number>;
  workload: Workload[];
  unassigned: Workload;
  trend: ({ date: string } & Record<string, string | number>)[];
  definitions: string[];
};
export const reportMetrics = [
  { key: "work_created", name: "新增工作项", color: "text-accent-primary", note: "包含正式需求和普通任务" },
  { key: "work_completed", name: "完成工作项", color: "text-success-primary", note: "区间内有完成记录的工作项" },
  { key: "test_executions", name: "测试执行", color: "text-accent-primary", note: "保留每次通过、失败等执行" },
  { key: "manual_executions", name: "人工验证", color: "text-accent-primary", note: "区间内实际提交的人工验证记录" },
  { key: "plans_confirmed", name: "确认测试计划", color: "text-success-primary", note: "经理确认，不等于全部通过" },
  { key: "defects_created", name: "新增缺陷", color: "text-warning-primary", note: "按创建时间" },
  { key: "defects_closed", name: "关闭缺陷", color: "text-success-primary", note: "按关闭记录，缺陷去重" },
  { key: "defects_reopened", name: "重新打开", color: "text-danger-primary", note: "按重开记录，缺陷去重" },
] as const;
