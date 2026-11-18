import { sortBy } from "lodash-es";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { fieldClass } from "@/components/quality/shared";
import { agentRunStatusLabel, remoteDiagnosticsBase, runningAgentStatuses } from "./types";
import type { AgentRun, RemoteDevice } from "./types";
import { FeedbackPicker } from "./feedback-picker";
import type { FeedbackChoice } from "./feedback-picker";

function resultText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无结果";
  if (Array.isArray(value)) return value.map(String).join("\n");
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export function AgentPanel({ device }: { device: RemoteDevice }) {
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackChoice>();
  const defectId = selectedFeedback?.id || "";
  const [problem, setProblem] = useState("");
  const [starting, setStarting] = useState(false);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [error, setError] = useState("");
  const [historyPage, setHistoryPage] = useState(1);
  const historyUrl = `/api/workspaces/${device.workspace_slug}/projects/${device.project_id}/quality/defects/${defectId}/collaboration/`;
  const {
    data: replies,
    error: historyError,
    mutate: refreshHistory,
  } = useSWR(defectId ? historyUrl : null, (url: string) =>
    qualityApi.all<{ id: string; content: string; visibility: string; created_at: string }>(url)
  );
  const history = sortBy(
    (replies || []).filter(
      (reply) => reply.visibility === "public" && /^Agent 远程处理：(已修复|验证通过|未自动修复)\n/.test(reply.content)
    ),
    (reply) => -Date.parse(reply.created_at)
  );
  const mountedRef = useRef(true);
  const submitting = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const busy = starting || !!(run && runningAgentStatuses.has(run.status));
  const runId = run?.id;
  const runInProgress = !!(run && runningAgentStatuses.has(run.status));
  const verified =
    run?.status === "completed" && run.result?.verification_passed === true && run.result?.outcome === "verified";

  useEffect(() => {
    if (runId && !runInProgress) submitting.current = false;
    if (!runId || !runInProgress) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const endpoint = `${remoteDiagnosticsBase}agent-runs/${encodeURIComponent(runId)}/`;
    async function poll() {
      try {
        const next = await qualityApi.read<AgentRun>(endpoint);
        if (cancelled) return;
        setError("");
        setRun(next);
        if (!runningAgentStatuses.has(next.status)) void refreshHistory();
        if (runningAgentStatuses.has(next.status)) timer = setTimeout(() => void poll(), 1500);
      } catch (cause) {
        if (!cancelled) {
          setError(`诊断状态读取失败，正在重试：${errorMessage(cause)}`);
          timer = setTimeout(() => void poll(), 5000);
        }
      }
    }
    timer = setTimeout(() => void poll(), 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [runId, runInProgress, refreshHistory]);

  async function start() {
    if (submitting.current || busy || !device.online || !device.can_connect || !defectId || !problem.trim()) return;
    submitting.current = true;
    setStarting(true);
    setError("");
    try {
      const next = await qualityApi.write<AgentRun>(`${remoteDiagnosticsBase}agent-runs/`, {
        device_id: device.id,
        defect_id: defectId,
        problem: problem.trim(),
      });
      if (mountedRef.current) setRun(next);
    } catch (cause) {
      submitting.current = false;
      if (mountedRef.current) setError(errorMessage(cause));
    } finally {
      if (mountedRef.current) setStarting(false);
    }
  }

  return (
    <section aria-label="Agent 诊断" className="space-y-4 rounded border border-subtle p-4 sm:p-5">
      <div>
        <h2 className="text-14 font-medium">Agent 诊断</h2>
        <p className="mt-1 text-13 text-secondary">关联原始反馈后开始排查，处理结果会回写到这条反馈。</p>
      </div>
      <FeedbackPicker
        device={device}
        value={selectedFeedback}
        disabled={busy}
        onChange={(value) => {
          setSelectedFeedback(value);
          setHistoryPage(1);
          setRun(null);
          setError("");
        }}
      />
      {defectId && (
        <section aria-label="所选反馈处理历史" className="space-y-3 rounded border border-subtle bg-surface-2 p-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="min-w-0 truncate text-13 font-medium" title={selectedFeedback?.title}>
              {selectedFeedback?.code} · 处理历史
            </h3>
            <button
              type="button"
              onClick={() => void refreshHistory()}
              className="shrink-0 text-12 text-accent-primary"
            >
              刷新历史
            </button>
          </div>
          <p className="text-12 text-secondary">新一轮处理会追加到原反馈，保留之前的结果。</p>
          {historyError ? (
            <p role="alert" className="text-12 text-danger-primary">
              无法读取历史：{errorMessage(historyError)}
            </p>
          ) : !replies ? (
            <p role="status" className="text-12 text-secondary">
              正在读取历史…
            </p>
          ) : !history.length ? (
            <p className="text-12 text-secondary">尚无 Agent 处理记录。</p>
          ) : (
            history.slice((historyPage - 1) * 3, historyPage * 3).map((reply, index) => {
              const [header, ...lines] = reply.content.split("\n");
              const repaired = header === "Agent 远程处理：已修复";
              const verifiedHistory = header === "Agent 远程处理：验证通过";
              return (
                <details
                  key={reply.id}
                  open={index === 0}
                  className="rounded border border-subtle bg-surface-1 px-3 py-2"
                >
                  <summary className="cursor-pointer text-12">
                    <span className={repaired || verifiedHistory ? "text-success-primary" : "text-warning-primary"}>
                      {repaired ? "已修复" : verifiedHistory ? "验证正常" : "需跟进"}
                    </span>
                    <time className="ml-3 text-secondary" dateTime={reply.created_at}>
                      {new Date(reply.created_at).toLocaleString("zh-CN", { hour12: false })}
                    </time>
                  </summary>
                  <p className="mt-2 text-12 leading-6 break-words whitespace-pre-wrap">{lines.join("\n")}</p>
                </details>
              );
            })
          )}
          {history.length > 3 && (
            <div className="flex items-center gap-3 text-12 text-secondary">
              <button type="button" disabled={historyPage === 1} onClick={() => setHistoryPage(historyPage - 1)}>
                上一页
              </button>
              <span>
                {historyPage} / {Math.ceil(history.length / 3)} · 共 {history.length} 轮
              </span>
              <button
                type="button"
                disabled={historyPage * 3 >= history.length}
                onClick={() => setHistoryPage(historyPage + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </section>
      )}
      <label className="flex flex-col gap-2 text-13">
        问题描述
        <textarea
          className={`${fieldClass} min-h-24`}
          maxLength={8000}
          value={problem}
          disabled={busy}
          placeholder="例如：采集开始后摄像头无画面，请定位原因并给出验证结果。"
          onChange={(event) => setProblem(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={busy || !device.online || !device.can_connect || !defectId || !problem.trim()}
        onClick={() => void start()}
        className="rounded bg-accent-primary px-4 py-2 text-13 text-on-color disabled:cursor-not-allowed disabled:opacity-50"
      >
        {starting ? "正在发起…" : busy ? "正在诊断…" : "开始诊断"}
      </button>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {run && (
        <div className="space-y-3 border-t border-subtle pt-4">
          <p role="status" className="text-13 font-medium">
            <span
              className={`inline-flex rounded px-2 py-1 text-12 ${runInProgress ? "bg-accent-subtle text-accent-primary" : run.status === "failed" ? "bg-surface-2 text-danger-primary" : run.result?.repaired === true || verified ? "bg-surface-2 text-success-primary" : "bg-surface-2 text-warning-primary"}`}
            >
              {agentRunStatusLabel(run)}
            </span>
            {run.status === "completed" && (
              <span className="font-normal ml-2 text-12 text-secondary">
                {run.result?.repaired === true ? "已修复" : verified ? "验证正常" : "未自动修复"}
              </span>
            )}
          </p>
          {run.error && (
            <p role="alert" className="text-13 whitespace-pre-wrap text-danger-primary">
              {run.error}
            </p>
          )}
          {run.result &&
            (
              Object.entries({
                summary: "摘要",
                root_cause: "原因",
                actions: "操作",
                verification: "验证",
                solution: "下一步",
              }) as [keyof NonNullable<AgentRun["result"]>, string][]
            ).map(([key, label]) => (
              <div key={key} className="grid gap-1 sm:grid-cols-[4rem_minmax(0,1fr)] sm:gap-4">
                <h3 className="text-13 font-medium text-secondary">{label}</h3>
                <p className="text-13 leading-6 break-words whitespace-pre-wrap">{resultText(run.result?.[key])}</p>
              </div>
            ))}
        </div>
      )}
    </section>
  );
}
