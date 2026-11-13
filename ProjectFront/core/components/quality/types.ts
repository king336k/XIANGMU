// SPDX-License-Identifier: AGPL-3.0-only
export type Step = { action: string; expected: string };
export type TestCase = {
  code?: string;
  number?: number;
  created_by_name?: string;
  created_at?: string;
  trashed_at: string | null;
  archived_at: string | null;
  id: string;
  title: string;
  module: string;
  priority: string;
  preconditions: string;
  steps: Step[];
  regression_request?: RegressionRequest;
  version: number;
  requirement_id: string | null;
  requirement_title: string | null;
};
export type Revision = { id: string; version: number; title: string; snapshot: TestCase; created_at: string };
export type Result = "passed" | "failed" | "blocked" | "inconclusive" | "skipped";
export type RegressionRequest = {
  test_target: string;
  verification_steps: Step[];
  environment: string;
  environment_details: Record<string, unknown>;
  approved_verification: string;
};
export type Execution = {
  reason_category: "" | "recollection" | "environment" | "other";
  next_action: string;
  code?: string;
  number?: number;
  id: string;
  item_id: string;
  plan_id?: string;
  result: Result;
  actual_result: string;
  evidence: string;
  step_results: { result: Result; actual: string }[];
  created_at: string;
  executor: string;
  case_title: string;
  case_id: string;
  case_version: number;
  plan_name: string;
  build: string;
  environment: string;
};
export type PlanItem = {
  current_case_version: number;
  case_archived: boolean;
  id: string;
  case_id: string;
  revision: Revision;
  latest_execution: Execution | null;
};
export type Summary = Record<Result | "pending" | "total" | "executed" | "pass_rate" | "execution_rate", number>;
export type Plan = {
  code?: string;
  number?: number;
  created_by_id?: string | null;
  created_by_name?: string;
  created_at?: string;
  archived_at: string | null;
  data_regression: {
    id: string;
    defect_id: string;
    round_started_at: string;
    task_id: number;
    request_snapshot: RegressionRequest | Record<string, never>;
  } | null;
  managed: boolean;
  status: string;
  round_no: number;
  workflow_version: number;
  assignee_id: string | null;
  workflow_events: {
    id: string;
    action: string;
    previous_status: string;
    status: string;
    round_no: number;
    note: string;
    actor: string;
    created_at: string;
  }[];
  id: string;
  name: string;
  build: string;
  environment: string;
  description: string;
  items: PlanItem[];
  summary: Summary;
  assignee_name: string;
};
export type Defect = {
  module?: { key: string; name: string } | null;
  assignment_origin?: "manual" | "diagnostic" | "initial" | "triage" | "";
  assignment_reason?: string;
  reporter?: { id: number; username: string };
  has_verification?: boolean;
  responsible_department?: string;
  component?: string;
  code?: string;
  number?: number;
  created_by_id?: string | null;
  created_by_name?: string;
  created_at?: string;
  source_kind?: "daq" | "test" | "manual";
  resolution_kind: string;
  duplicate_of_id: string | null;
  defer_until: string | null;
  archived_at: string | null;
  edit_version: number;
  pending_assignee_id: string | null;
  transfer_reason: string;
  collaborators: { user_id: string; name: string }[];
  assignee_name: string;
  manual_verification_allowed: boolean;
  verification_scope?: "auto" | "functional" | "data";
  requires_data_regression?: boolean;
  id: string;
  title: string;
  severity: string;
  description: string;
  status: string;
  affected_build: string;
  fixed_build: string;
  resolved_at: string | null;
  resolution: string;
  case_id: string | null;
  case_title: string | null;
  assignee_id: string | null;
  repair_issue_id: string | null;
  repair_issue_name: string | null;
  repair_issue_sequence: number | null;
  source_execution: Execution | null;
  regression_execution: Execution | null;
  events: { id: string; previous_status: string; status: string; note: string; created_at: string; actor: string }[];
};
export type Context = {
  work_item_options_url?: string;
  business_role: string | null;
  business_roles?: string[];
  business_role_name: string;
  business_roles_enabled: boolean;
  capabilities: Record<string, boolean>;
  user_id: string;
  is_manager: boolean;
  is_administrator?: boolean;
  can_manage_administrators?: boolean;
  can_review_knowledge?: boolean;
  can_configure_model?: boolean;
  project_name: string;
  identifier: string;
  can_write: boolean;
  members: {
    id: string;
    name: string;
    business_role?: string | null;
    business_roles?: string[];
    is_administrator?: boolean;
  }[];
  issues: { id: string; name: string; sequence_id: number }[];
};
export type Page<T> = { results: T[]; count: number; next: string | null; previous: string | null };
export type Report = {
  manual_verification?: Summary;
  manual_execution_count?: number;
  historical_plan_count?: number;
  summary: Summary;
  case_count: number;
  plan_count: number;
  execution_count: number;
  open_defects: number;
  closed_defects?: number;
  requirement_linked_cases: number;
  definitions: Record<string, string>;
};
export const resultNames: Record<string, string> = {
  passed: "通过",
  failed: "失败",
  blocked: "阻塞",
  inconclusive: "无法判定",
  skipped: "跳过",
  pending: "未执行",
};
export const reasonNames: Record<string, string> = {
  recollection: "需要补采",
  environment: "环境待处理",
  other: "其他",
};
export const statusNames: Record<string, string> = {
  open: "待处理",
  in_progress: "处理中",
  resolved: "已修复，待回归",
  closed: "已关闭",
};
export const severityNames: Record<string, string> = {
  critical: "致命",
  major: "严重",
  minor: "一般",
  trivial: "轻微",
};
export const priorityNames: Record<string, string> = { high: "高", medium: "中", low: "低" };

export const planStatusNames: Record<string, string> = {
  pending: "待分派",
  ready: "待认领",
  running: "测试中",
  paused: "已暂停",
  review: "待确认测试结果",
  completed: "测试结果已确认",
  returned: "已退回，待复测",
  cancelled: "已取消",
  failed: "回归失败，待修复",
};

export function can(context: Context, capability: string): boolean {
  return context.can_write && (!context.business_roles_enabled || context.capabilities[capability] === true);
}

export function canOpenQualityTab(context: Context | undefined, tab: string): boolean {
  if (!context) return false;
  return (
    !["roles", "integrations"].includes(tab) ||
    (context.can_write && (context.is_manager || (context.business_roles_enabled && can(context, "manage_roles"))))
  );
}

export function canOpenKnowledgeTab(context: Context | undefined, tab: string): boolean {
  if (!context) return false;
  if (tab === "settings") return context.can_configure_model === true;
  if (["editorial", "governance"].includes(tab))
    return context.can_review_knowledge === true || can(context, "knowledge_write");
  return true;
}

export function defectDisplayTitle(title: string): string {
  const categories: Record<string, string> = {
    DataAnomaly: "数据异常",
    UploadError: "上传异常",
    ValidationFailed: "校验失败",
    TimestampAnomaly: "时间戳异常",
    Other: "其他异常",
  };
  return title.replace(
    /^(DataAnomaly|UploadError|ValidationFailed|TimestampAnomaly|Other):\s*/,
    (_, category: string) => `${categories[category]}：`
  );
}
