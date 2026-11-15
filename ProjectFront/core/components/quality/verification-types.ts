import type { Execution, Step } from "./types";
export type VerificationItem = {
  item_id: string;
  case_id?: string | null;
  case_version?: number | null;
  revision_id?: string | null;
  source?: "library" | "round" | "legacy";
  title: string;
  snapshot: { title: string; steps: Step[]; preconditions?: string; module?: string; priority?: string };
  stale: boolean;
  latest_execution: Execution | null;
  execution_history?: Execution[];
  result: string;
};
export type VerificationRound = {
  id: string;
  defect_id: string;
  round_no: number;
  version: number;
  mode: "manual" | "cases";
  status: string;
  execution_state?: string;
  blocked_reason?: string;
  assignee_id?: string | null;
  assignee_name?: string;
  fixed_build: string;
  environment: string;
  steps: Step[];
  test_requirements?: string;
  plan_id: string | null;
  created_at: string;
  items: VerificationItem[];
  summary: Record<string, number>;
  manual_results: {
    id: string;
    result: string;
    actual_result: string;
    created_by_id?: string | null;
    created_by_name?: string;
    evidence: string;
    created_at: string;
    step_results: { result: string; actual: string }[];
    reason_category: string;
    next_action: string;
  }[];
  events: { action: string; note: string; actor: string; created_at: string; round_no: number }[];
  can_configure: boolean;
  can_record: boolean;
  can_submit: boolean;
  can_accept: boolean;
  can_return_test: boolean;
  can_return_repair: boolean;
  can_reopen: boolean;
};
export type VerificationData = {
  defect_id: string;
  defect_status: string;
  defect_version: number;
  current: VerificationRound | null;
  history: VerificationRound[];
};
export function verificationNextStep(round: VerificationRound): string {
  if (round.status === "accepted") return "验收完成";
  if (["returned_repair", "reopened"].includes(round.status)) return "待技术负责人修复后重新安排";
  if (round.status === "review") {
    if (!round.can_accept && !round.can_return_test) return "等待项目经理或管理员验收";
    return round.summary.total > 0 && round.summary.passed === round.summary.total
      ? "验收关闭，或退回补测"
      : "查看未通过项，退回补测或修复";
  }
  if (round.execution_state === "waiting_repair") return "待技术负责人登记修复后测试";
  if (round.execution_state === "needs_arrangement") return round.can_configure ? "重新安排测试" : "等待负责人重新安排";
  if (round.execution_state === "needs_assignment") return round.can_configure ? "指派测试员" : "等待负责人指派测试员";
  if (round.execution_state === "needs_cases")
    return round.can_record || round.can_configure ? "补充本轮用例" : "等待补充本轮用例";
  if (!round.can_record) return `等待 ${round.assignee_name || "指派测试员"} 测试`;
  if (round.summary.total > 0 && round.summary.pending === 0) return "提交验收";
  return round.mode === "manual" ? "填写测试结果" : `执行剩余 ${round.summary.pending} 条用例`;
}
export const verificationStatus: Record<string, string> = {
  waiting_repair: "等待修复",
  needs_arrangement: "待重新安排",
  needs_assignment: "待安排测试员",
  needs_cases: "待补充用例",
  pending: "待测试",
  running: "测试中",
  tested: "已测试，待提交",
  testing: "待验证",
  review: "待验收",
  accepted: "已验收",
  returned_test: "退回补测",
  returned_repair: "退回修复",
  reopened: "已重新打开",
  superseded: "已调整",
};

export const verificationStatusTone: Record<string, string> = {
  waiting_repair: "pending",
  needs_arrangement: "blocked",
  needs_assignment: "pending",
  needs_cases: "pending",
  pending: "pending",
  running: "running",
  tested: "passed",
  testing: "running",
  review: "review",
  accepted: "passed",
  returned_test: "failed",
  returned_repair: "failed",
  reopened: "running",
  superseded: "neutral",
};
