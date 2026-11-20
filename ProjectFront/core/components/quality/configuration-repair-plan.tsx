// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { RotateCw } from "lucide-react";
import { qualityApi, errorMessage } from "./api";
import { ConfigurationPlanResult } from "./configuration-plan-result";
import { remoteDiagnosticsBase } from "../remote-diagnostics/types";
import type { AgentRun } from "../remote-diagnostics/types";

type Change = { key: string; before?: unknown; after?: unknown; before_line?: number; after_line?: number };
export type ConfigurationRepairProposal = {
  source_run_id: string;
  plan_digest: string;
  robot: string;
  observed_at: string;
  expires_at: string;
  device: { username: string; ip_address?: string };
  path: string;
  changes: Change[];
  can_approve: boolean;
  blocked_reason?: string;
  submitted_run?: AgentRun | null;
};
type ProposalResponse = { proposal: ConfigurationRepairProposal | null };

function displayValue(input: unknown) {
  return typeof input === "string" ? input : JSON.stringify(input);
}
function blockedMessage(reason?: string) {
  if (reason && /[\u3400-\u9fff]/u.test(reason)) return reason;
  return (
    (
      {
        executor_update_required: "执行端需要更新后才能接收修复计划。",
        baseline_not_approved_for_device: "当前设备还没有可追溯的批准依据。",
        proposal_expired: "修复计划已过期，请重新诊断。",
        snapshot_changed: "现场配置已变化，请重新诊断。",
      } as Record<string, string>
    )[reason || ""] || "当前修复计划不能执行，请重新诊断。"
  );
}

export function ConfigurationRepairPlan({
  defectId,
  disabled = false,
  run,
  onHistory,
  onRestoredRun,
  onSubmitted,
  onSubmitting,
  onSettled,
}: {
  defectId: string;
  disabled?: boolean;
  run?: AgentRun | null;
  onHistory?: () => void;
  onRestoredRun?: (run: AgentRun) => void;
  onSubmitted?: (run: AgentRun) => void;
  onSubmitting?: () => boolean;
  onSettled?: (accepted: boolean) => void;
}) {
  const { data, error: readError } = useSWR<ProposalResponse>(
    defectId ? `${remoteDiagnosticsBase}configuration-plans/?defect_id=${encodeURIComponent(defectId)}` : null,
    (url: string) => qualityApi.read<ProposalResponse>(url),
    { refreshInterval: disabled ? 0 : 10000 }
  );
  const proposal = data?.proposal || null;
  const [expanded, setExpanded] = useState(false);
  const [confirmedDigest, setConfirmedDigest] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const digest = proposal?.plan_digest || "";
  const pending = useRef("");
  const [acceptedRun, setAcceptedRun] = useState<AgentRun | null>(null);
  const restoredRunId = useRef("");
  const restoredRun = proposal?.submitted_run;
  useEffect(() => {
    if (restoredRun && restoredRun.can_follow !== false && restoredRun.id !== restoredRunId.current) {
      restoredRunId.current = restoredRun.id;
      onRestoredRun?.(restoredRun);
    }
  }, [restoredRun, onRestoredRun]);
  const resultRun = run || acceptedRun || restoredRun;
  if (!proposal)
    return resultRun ? (
      <ConfigurationPlanResult run={resultRun} onHistory={onHistory} />
    ) : readError ? (
      <p role="status" className="text-11 text-warning-primary">
        修复计划暂时无法读取，请稍后重试。
      </p>
    ) : null;
  const plan = proposal;
  const expired = !Number.isFinite(Date.parse(plan.expires_at)) || Date.parse(plan.expires_at) <= Date.now();
  const confirmed = confirmedDigest === digest && !!digest;
  const canApprove = proposal.can_approve && !expired && !disabled && !submitting && pending.current !== digest;
  const status = submitting
    ? "提交中"
    : pending.current === digest || (!proposal.can_approve && /已提交/u.test(proposal.blocked_reason || ""))
      ? "已提交"
      : expired
        ? "已失效"
        : !proposal.can_approve
          ? /DAQ|更新|update_required/iu.test(proposal.blocked_reason || "")
            ? "需更新"
            : "暂不可执行"
          : "待确认";
  async function submit() {
    if (!canApprove || !confirmed || pending.current === digest || Date.parse(plan.expires_at) <= Date.now()) return;
    if (onSubmitting?.() === false) return;
    pending.current = digest;
    setSubmitting(true);
    setError("");
    let accepted = false;
    try {
      const submitted = await qualityApi.write<AgentRun>(`${remoteDiagnosticsBase}configuration-plans/`, {
        source_run_id: plan.source_run_id,
        plan_digest: plan.plan_digest,
        confirmation: "confirmed",
      });
      accepted = true;
      setAcceptedRun(submitted);
      onSubmitted?.(submitted);
    } catch (cause) {
      pending.current = "";
      setError(errorMessage(cause));
    } finally {
      setSubmitting(false);
      onSettled?.(accepted);
    }
  }
  return (
    <section className="rounded border border-subtle bg-surface-1" aria-label="配置修复计划">
      <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary
          aria-expanded={expanded}
          className="focus-visible:ring-accent-primary cursor-pointer px-3 py-2 text-13 font-semibold text-primary outline-none focus-visible:ring-2"
        >
          配置修复计划
          <span
            role="status"
            className={`font-normal ml-2 inline-block rounded px-1.5 py-0.5 align-middle text-11 ${status === "待确认" ? "bg-warning-subtle text-warning-primary" : "bg-surface-2 text-secondary"}`}
          >
            {status}
          </span>
          <span className="font-normal mt-0.5 block pl-4 text-11 text-secondary">
            {proposal.device.username}@{proposal.device.ip_address || "IP待确认"} · {proposal.robot}
          </span>
        </summary>
        {expanded && (
          <div className="space-y-3 border-t border-subtle px-3 py-3">
            <p className="font-mono text-12 break-all">{proposal.path}</p>
            <div className="overflow-hidden rounded border border-subtle">
              <div className="grid grid-cols-2 text-11">
                <div className="bg-danger-subtle px-3 py-1.5 text-danger-primary">修改前</div>
                <div className="border-l border-subtle bg-success-subtle px-3 py-1.5 text-success-primary">修改后</div>
              </div>
              {proposal.changes.map((change) => (
                <div key={change.key} className="font-mono grid grid-cols-2 border-t border-subtle text-12">
                  <div className="min-w-0 bg-danger-subtle px-3 py-2 break-words">
                    {change.key}: {displayValue(change.before)}
                  </div>
                  <div className="min-w-0 border-l border-subtle bg-success-subtle px-3 py-2 break-words">
                    {change.key}: {displayValue(change.after)}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-11 text-secondary">仅修改所列字段并复查，不执行机器人复位、运动或采集验收。</p>
            {(!proposal.can_approve || expired) && (
              <p role="status" className="text-11 text-warning-primary">
                {blockedMessage(expired ? "proposal_expired" : proposal.blocked_reason)}
              </p>
            )}
            {proposal.can_approve && (
              <label className="flex items-start gap-2 text-11 text-secondary">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={submitting || disabled || expired}
                  onChange={(event) => setConfirmedDigest(event.target.checked ? digest : "")}
                />
                <span>我确认以上修改值适用于当前机器人，并授权平台按此计划处理。</span>
              </label>
            )}
            <button
              type="button"
              disabled={!confirmed || !canApprove}
              onClick={submit}
              className="inline-flex items-center rounded bg-accent-primary px-3 py-1.5 text-12 text-on-color disabled:opacity-40"
            >
              {submitting && (
                <RotateCw aria-hidden="true" className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" />
              )}
              {submitting ? "提交中" : "确认修复"}
            </button>
            {(error || readError) && (
              <p role="alert" className="text-11 text-danger-primary">
                {error || errorMessage(readError)}
              </p>
            )}
          </div>
        )}
      </details>
      {resultRun && <ConfigurationPlanResult run={resultRun} onHistory={onHistory} />}
    </section>
  );
}
