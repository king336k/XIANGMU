// SPDX-License-Identifier: AGPL-3.0-only
export type FlowNode = {
  id: string;
  name: string;
  kind: "issue" | "requirement" | "plan" | "defect" | "milestone";
  object_id?: string;
  owner_id?: string | null;
  depends_on: string[];
  join: "all" | "any";
  required: boolean;
  target_date?: string | null;
};
export type FlowState = {
  status: string;
  business_status: string;
  manual_completed: boolean;
  dispatched: boolean;
  notice: string;
};
export type VersionSummary = {
  code?: string;
  number?: number;
  created_by_name?: string;
  id: string;
  name: string;
  version: string;
  description: string;
  status: string;
  start_date: string | null;
  target_date: string | null;
  owner_id: string | null;
  owner_name: string;
  cycle_id: string | null;
  cycle_name: string;
  edit_version: number;
  automation_enabled: boolean;
};
export type VersionDetail = VersionSummary & {
  quality_release_id: string | null;
  automation_note: string;
  flow_nodes: FlowNode[];
  flow_state: Record<string, FlowState>;
  blockers: string[];
  published_at: string | null;
  requirements: { id: string; name: string; status: string; code: string; version: number }[];
  tasks: {
    id: string;
    code?: string;
    name: string;
    status: string;
    done: boolean;
    start_date: string | null;
    target_date: string | null;
  }[];
  plans: { id: string; name: string; status: string; code?: string }[];
  defects: { id: string; name: string; status: string; code?: string }[];
  event_pagination: { count: number; page: number; per_page: number };
  events: { id: string; action: string; note: string; status: string; created_at: string; actor: string }[];
};
export const versionStatuses: Record<string, string> = {
  planning: "规划中",
  development: "开发中",
  testing: "测试中",
  ready: "待发布",
  released: "已发布",
  cancelled: "已取消",
};
export const nodeKinds: Record<FlowNode["kind"], string> = {
  issue: "开发任务",
  requirement: "需求验收",
  plan: "测试计划",
  defect: "缺陷处理",
  milestone: "里程碑",
};
export const flowStatuses: Record<string, string> = {
  waiting: "等待前置",
  ready: "可以开始",
  completed: "已完成",
  blocked: "需处理关联",
};
