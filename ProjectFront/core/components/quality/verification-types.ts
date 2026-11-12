import type { Execution, Step } from "./types";
export type VerificationItem = {
  item_id: string;
  case_id: string;
  case_version: number;
  revision_id: string;
  title: string;
  snapshot: { title: string; steps: Step[]; preconditions?: string; module?: string; priority?: string };
  stale: boolean;
  latest_execution: Execution | null;
  result: string;
};
export type VerificationRound = {
  id: string;
  defect_id: string;
  round_no: number;
  version: number;
  mode: "manual" | "cases";
  status: string;
  fixed_build: string;
  environment: string;
  steps: Step[];
  plan_id: string | null;
  created_at: string;
  items: VerificationItem[];
  summary: Record<string, number>;
  manual_results: {
    id: string;
    result: string;
    actual_result: string;
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
export const verificationStatus: Record<string, string> = {
  testing: "待验证",
  review: "待验收",
  accepted: "已验收",
  returned_test: "退回补测",
  returned_repair: "退回修复",
  reopened: "已重新打开",
  superseded: "已调整",
};
