// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { agentRunStatusLabel, remoteDiagnosticsBase, runningAgentStatuses } from "../remote-diagnostics/types";
import type { AgentRun, RemoteDevice } from "../remote-diagnostics/types";

export function AgentFeedbackActions({
  defectId,
  active,
  onCompleted,
  onHistory,
}: {
  defectId: string;
  active: boolean;
  onCompleted: () => void;
  onHistory: () => void;
}) {
  const { data: targets, error: targetError } = useSWR(
    active ? `${remoteDiagnosticsBase}defect-targets/?defect_id=${defectId}` : null,
    (url: string) => qualityApi.read<{ results: RemoteDevice[] }>(url),
    { refreshInterval: active ? 10000 : 0 }
  );
  const [deviceId, setDeviceId] = useState("");
  const [runId, setRunId] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [submittedRun, setSubmittedRun] = useState<AgentRun | null>(null);
  const submitting = useRef(false);
  const { data: runSnapshot, error: runError } = useSWR(
    runId ? `${remoteDiagnosticsBase}agent-runs/${runId}/` : null,
    (url: string) => qualityApi.read<AgentRun>(url),
    { refreshInterval: (value) => (value && runningAgentStatuses.has(value.status) ? 1500 : 0) }
  );
  const run = runSnapshot || submittedRun;
  const completed = useRef("");
  useEffect(() => {
    if (run && !runningAgentStatuses.has(run.status) && completed.current !== run.id) {
      submitting.current = false;
      completed.current = run.id;
      onCompleted();
    }
  }, [run, onCompleted]);
  const choices = targets?.results || [];
  const selected = choices.find((device) => device.id === (deviceId || (choices.length === 1 ? choices[0].id : "")));
  const busy = starting || !!(run && runningAgentStatuses.has(run.status));
  async function start(mode: string) {
    if (submitting.current || !selected?.online || busy) return;
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
        {choices.length > 1 && (
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
          disabled={busy || !selected?.online}
          onClick={() => void start("diagnose")}
          className="rounded border border-subtle px-3 py-1.5 text-12 disabled:opacity-40"
        >
          重新诊断（只读）
        </button>
        <button
          type="button"
          disabled={busy || !selected?.online}
          onClick={() => void start("repair")}
          className="rounded bg-accent-primary px-3 py-1.5 text-12 text-on-color disabled:opacity-40"
        >
          诊断并修复
        </button>
        <button
          type="button"
          disabled={busy || !selected?.online}
          onClick={() => void start("verify")}
          className="rounded border border-subtle px-3 py-1.5 text-12 disabled:opacity-40"
        >
          重新验证（只读）
        </button>
        <button type="button" onClick={onHistory} className="px-2 py-1.5 text-12 text-accent-primary">
          查看处理过程
        </button>
        {(starting || run) && (
          <span
            role="status"
            className={`rounded px-2 py-1 text-12 ${busy ? "bg-accent-subtle text-accent-primary" : run?.status === "failed" || run?.status === "timed_out" ? "bg-danger-subtle text-danger-primary" : run?.result?.verification_passed === true && (run.result.repaired === true || run.result.outcome === "verified") ? "bg-success-subtle text-success-primary" : "bg-surface-2 text-secondary"}`}
          >
            {starting ? "正在提交…" : run ? agentRunStatusLabel(run) : ""}
          </span>
        )}
      </div>
      <p className="text-11 text-secondary">
        诊断并修复：同一任务完成排查、授权修复、自动复测和原反馈回写；只读操作不修改现场。
      </p>
      {selected && (
        <p className="text-11 text-secondary">
          现场：{selected.username}@{selected.ip_address || "IP待确认"}
          {selected.online ? "" : " · 当前离线"}；自动修复仅在已授权范围内执行。
        </p>
      )}
      {targets && !choices.length && <p className="text-12 text-secondary">此反馈尚未关联已接入的采集电脑。</p>}
      {(error || targetError || runError || run?.error) && (
        <p role="alert" className="text-12 text-danger-primary">
          {error || (targetError || runError ? errorMessage(targetError || runError) : run?.error)}
        </p>
      )}
    </div>
  );
}
