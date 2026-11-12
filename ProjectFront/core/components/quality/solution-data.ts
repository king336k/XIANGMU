export type SolutionReview = {
  id: string;
  created_by_id?: string;
  actor: string;
  decision: string;
  comment: string;
  created_at?: string;
};
export type SolutionRevision = {
  id: string;
  version: number;
  snapshot: Record<string, string>;
  reviewer_ids: string[];
  required_count: number;
  reviews: SolutionReview[];
  created_at?: string;
  created_by_name?: string;
};
export type Solution = {
  id: string;
  defect_id: string;
  title: string;
  status: string;
  edit_version: number;
  submitted_version?: number;
  created_by_id: string;
  created_by_name?: string;
  created_at?: string;
  contributor_ids?: string[];
  revisions: SolutionRevision[];
  root_cause: string;
  steps: string;
  verification: string;
  risk: string;
  rollback: string;
  repository: string;
  commit_sha: string;
  can_edit: boolean;
  can_submit: boolean;
  can_review: boolean;
  current_revision_id?: string | null;
  current_revision_version?: number | null;
};
export const solutionFields = [
  { key: "root_cause", label: "根因分析", required: true },
  { key: "steps", label: "解决步骤", required: true },
  { key: "verification", label: "验证方法", required: true },
  { key: "risk", label: "影响与风险", required: false },
  { key: "rollback", label: "回退方法", required: false },
] as const;
export const solutionStatus: Record<string, string> = {
  draft: "草稿",
  review: "待审核",
  approved: "已通过",
  rejected: "已退回",
};
export const solutionTone: Record<string, string> = {
  draft: "neutral",
  review: "review",
  approved: "passed",
  rejected: "failed",
};
export function currentSolutionRevision(solution: Solution) {
  return solution.revisions.find((r) => r.id === solution.current_revision_id);
}
