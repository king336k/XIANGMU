// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { RotateCw } from "lucide-react";
import { qualityApi, errorMessage } from "./api";
import {
  agentRunShortLabel,
  agentRunStatusLabel,
  remoteDiagnosticsBase,
  runningAgentStatuses,
} from "../remote-diagnostics/types";
import type { AgentRun, RemoteDevice } from "../remote-diagnostics/types";

export function AgentFeedbackActions({
  defectId,
  active,
  onCompleted,
  onStarted,
  onHistory,
}: {
  defectId: string;
  active: boolean;
  onCompleted: () => void;
  onStarted?: () => void;
  onHistory: () => void;
}) {
  const { data: targets, error: targetError } = useSWR(
    active ? `${remoteDiagnosticsBase}defect-targets/?defect_id=${defectId}` : null,
    (url: string) =>
      qualityApi.read<{
        results: RemoteDevice[];
        active_run?: AgentRun | null;
        binding?: {
          kind: "daq" | "manual";
          state: "matched" | "missing" | "conflict";
          device_id?: string;
          source_instance?: string;
        };
      }>(url),
    { refreshInterval: active ? 10000 : 0 }
  );
  const [deviceId, setDeviceId] = useState("");
  const [runId, setRunId] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [submittedRun, setSubmittedRun] = useState<AgentRun | null>(null);
  const submitting = useRef(false);
  const effectiveRunId = runId || targets?.active_run?.id || "";
  const { data: runSnapshot, error: runError } = useSWR(
    effectiveRunId ? `${remoteDiagnosticsBase}agent-runs/${effectiveRunId}/` : null,
    (url: string) => qualityApi.read<AgentRun>(url),
    { refreshInterval: (value) => (value && runningAgentStatuses.has(value.status) ? 1500 : 0) }
  );
  const run = runSnapshot || submittedRun || targets?.active_run;
  const completed = useRef("");
  useEffect(() => {
    if (run && !runningAgentStatuses.has(run.status) && completed.current !== run.id) {
      submitting.current = false;
      completed.current = run.id;
      onCompleted();
    }
  }, [run, onCompleted]);
  const choices = targets?.results || [];
  const binding = targets?.binding;
  const sourceBound = binding?.kind === "daq";
  const manualBound = binding?.kind === "manual";
  const selected = sourceBound
    ? choices.find((device) => device.id === binding.device_id)
    : manualBound
      ? choices.find((device) => device.id === deviceId)
      : undefined;
  const bindingReady = binding?.state === "matched" && !!selected;
  const available = bindingReady && selected?.online === true;
  const connectionLabel =
    binding?.state === "conflict" ||
    (!sourceBound && !manualBound) ||
    (sourceBound && binding?.state === "matched" && !selected)
      ? "接入信息不一致"
      : available
        ? "在线"
        : "执行端断连";
  const busy = starting || !!(run && runningAgentStatuses.has(run.status));
  async function start(mode: string) {
    if (submitting.current || !available || !selected || busy) return;
    submitting.current = true;
    setStarting(true);
    setError("");
    try {
      const result = await qualityApi.write<AgentRun>(`${remoteDiagnosticsBase}agent-runs/`, {
        device_id: selected.id,
        defect_id: defectId,
        mode,
        problem:
          mode === "repair"
            ? "请重新读取当前现场证据，定位本反馈问题，在授权范围内最小修复并真实复测。无法修复时给出已证实根因、缺口及具体处理步骤。"
            : mode === "verify"
              ? "请只读复核本反馈当前现场状态，必须执行固定验证入口。禁止修改配置、文件或服务，如实记录验证证据。"
              : "请重新读取当前现场配置与日志，只读诊断本反馈问题，给出证据、根因、具体修复和验证建议；禁止修改配置、文件或服务。",
      });
      setSubmittedRun(result);
      setRunId(result.id);
      onStarted?.();
    } catch (cause) {
      submitting.current = false;
      setError(errorMessage(cause));
    } finally {
      setStarting(false);
    }
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {manualBound && choices.length > 0 && (
          <select
            aria-label="现场采集电脑"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            disabled={busy}
            className="rounded border border-subtle bg-surface-1 px-3 py-2 text-12"
          >
            <option value="">选择采集电脑</option>
            {choices.map((device) => (
              <option key={device.id} value={device.id}>
                {device.username}@{device.ip_address || "IP待确认"}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          disabled={busy || !available}
          title="重新诊断（只读，不修改现场）"
          onClick={() => void start("diagnose")}
          className="rounded border border-subtle px-3 py-1.5 text-12 disabled:opacity-40"
        >
          重新诊断
        </button>
        <button
          type="button"
          disabled={busy || !available}
          title="诊断、授权修复、自动复测和原反馈回写"
          onClick={() => void start("repair")}
          className="rounded bg-accent-primary px-3 py-1.5 text-12 text-on-color disabled:opacity-40"
        >
          继续处理
        </button>
        <button
          type="button"
          disabled={busy || !available}
          title="重新验证（只读，执行固定验证入口）"
          onClick={() => void start("verify")}
          className="rounded border border-subtle px-3 py-1.5 text-12 disabled:opacity-40"
        >
          重新验证
        </button>
        <button type="button" onClick={onHistory} className="px-2 py-1.5 text-12 text-accent-primary">
          查看处理
        </button>
        {(starting || run) && (
          <span
            role="status"
            aria-live="polite"
            title={run ? agentRunStatusLabel(run) : "正在提交现场处理任务"}
            className={`rounded px-2 py-1 text-12 ${busy ? "bg-accent-subtle text-accent-primary" : run?.status === "failed" || run?.status === "timed_out" ? "bg-danger-subtle text-danger-primary" : run?.result?.verification_passed === true && (run.result.repaired === true || ["verified", "verified_without_repair"].includes(run.result.outcome || "")) ? "bg-success-subtle text-success-primary" : "bg-surface-2 text-secondary"}`}
          >
            {busy && (
              <RotateCw
                aria-hidden="true"
                className="mr-1.5 inline-block size-3.5 animate-spin motion-reduce:animate-none"
              />
            )}
            {starting ? "排队中" : run ? agentRunShortLabel(run) : ""}
          </span>
        )}
      </div>
      <p className="text-11 text-secondary">
        {run && busy ? agentRunStatusLabel(run) : "同一任务完成排查、授权修复与复测；只读操作不修改现场。"}
      </p>
      {sourceBound && (
        <p role="status" className={`text-11 break-words ${available ? "text-secondary" : "text-warning-primary"}`}>
          采集电脑：{selected ? `${selected.username}@${selected.ip_address || "IP待确认"}` : "原采集端"} ·{" "}
          {connectionLabel}
        </p>
      )}
      {manualBound && selected && (
        <p className="text-11 break-words text-secondary">
          采集电脑：{selected.username}@{selected.ip_address || "IP待确认"} · {connectionLabel}
        </p>
      )}
      {targets && !binding && (
        <p role="status" className="text-11 text-warning-primary">
          接入信息不一致，请刷新绑定信息。
        </p>
      )}
      {manualBound && !selected && (
        <p className="text-11 text-secondary">
          {choices.length ? "请选择已关联的采集电脑。" : "请先在远程诊断中关联采集电脑。"}
        </p>
      )}
      {(error || targetError || runError || run?.error) && (
        <p role="alert" className="text-12 text-danger-primary">
          {error || (targetError || runError ? errorMessage(targetError || runError) : run?.error)}
        </p>
      )}
    </div>
  );
}
