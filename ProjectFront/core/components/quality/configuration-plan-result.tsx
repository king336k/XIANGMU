// SPDX-License-Identifier: AGPL-3.0-only
import { RotateCw } from "lucide-react";
import { agentRunShortLabel, agentRunStatusLabel, runningAgentStatuses } from "../remote-diagnostics/types";
import type { AgentRun } from "../remote-diagnostics/types";
import { AgentReportText } from "./agent-report-text";
import { compactReportText } from "./report-summary";

export function ConfigurationPlanResult({ run, onHistory }: { run: AgentRun; onHistory?: () => void }) {
  const busy = runningAgentStatuses.has(run.status);
  const result = run.result;
  const summary = typeof result?.summary === "string" ? compactReportText(result.summary, 220) : "";
  const blocked = result?.configuration_blocked_reason || "";
  const label = result?.actual_write === false && blocked ? "未修改" : agentRunShortLabel(run);
  const detail = [
    typeof result?.brief_report === "string" ? result.brief_report : "",
    ...(
      [
        ["原因", result?.root_cause],
        ["验证", result?.verification],
        ["下一步", result?.solution],
      ] as const
    )
      .map(
        ([name, value]) =>
          `${name}：${Array.isArray(value) ? value.join("；") : typeof value === "string" ? value : ""}`
      )
      .filter((line) => !line.endsWith("：")),
    typeof result?.evidence_details === "string" ? `详细依据：\n${result.evidence_details}` : "",
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <details className="border-t border-subtle px-3 py-3" aria-label="本次修复进度">
      <summary className="cursor-pointer text-12 font-semibold text-primary">
        <span role="status" aria-live="polite" className="inline-flex items-center gap-2 align-middle">
          {busy && <RotateCw aria-hidden="true" className="size-3.5 animate-spin motion-reduce:animate-none" />}
          <span className="font-semibold text-primary">本次修复</span>
          <span className={busy ? "text-accent-primary" : "text-secondary"}>{label}</span>
        </span>
      </summary>
      <div className="mt-2 space-y-2">
        {busy ? (
          <p className="text-12 text-secondary">{agentRunStatusLabel(run)}</p>
        ) : (
          <>
            {(blocked || summary) && <p className="text-12 leading-6 text-secondary">{blocked || summary}</p>}
            {result?.actual_write === false && !blocked && <p className="text-12 text-secondary">本轮未修改现场。</p>}
            {!summary && !blocked && run.error && (
              <p className="text-12 text-warning-primary">本轮处理未完成，请查看详细记录。</p>
            )}
          </>
        )}
        {detail && (
          <details>
            <summary className="cursor-pointer text-12 font-medium text-secondary">详细证据与处理过程</summary>
            <div className="mt-2 max-h-80 overflow-auto">
              <AgentReportText content={detail} />
            </div>
          </details>
        )}
        {onHistory && (
          <button type="button" onClick={onHistory} className="text-12 text-accent-primary">
            查看完整处理记录
          </button>
        )}
      </div>
    </details>
  );
}
