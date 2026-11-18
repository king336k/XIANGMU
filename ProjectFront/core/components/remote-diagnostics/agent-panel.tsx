import { sortBy } from "lodash-es";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { fieldClass } from "@/components/quality/shared";
import { agentStatusLabel, remoteDiagnosticsBase, runningAgentStatuses } from "./types";
import type { AgentRun, RemoteDevice } from "./types";

function resultText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无结果";
  if (Array.isArray(value)) return value.map(String).join("\n");
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export function AgentPanel({ device }: { device: RemoteDevice }) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [state, setState] = useState("needs_attention");
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams({ device_id: device.id, q: query, page: String(page), per_page: "20", state });
  const { data: feedback, error: feedbackError } = useSWR(
    `${remoteDiagnosticsBase}feedback/?${params}`,
    (url: string) =>
      qualityApi.read<{
        count: number;
        results: { id: string; title: string; code: string; latest_status?: string; run_count?: number }[];
      }>(url)
  );
  const [defectId, setDefectId] = useState("");
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
  const selectedFeedback = feedback?.results.find((item) => item.id === defectId);
  const mountedRef = useRef(true);
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
    if (busy || !device.online || !device.can_connect || !defectId || !problem.trim()) return;
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
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="搜索当前电脑的反馈"
          placeholder="反馈编号或关键词"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setDefectId("");
          }}
          disabled={busy}
          className={`${fieldClass} min-w-48 flex-1`}
        />
        <select
          aria-label="反馈处理状态"
          value={state}
          disabled={busy}
          onChange={(event) => {
            setState(event.target.value);
            setPage(1);
            setDefectId("");
          }}
          className={`${fieldClass} w-auto`}
        >
          <option value="needs_attention">待处理与未解决</option>
          <option value="running">处理中</option>
          <option value="repaired">已修复并验证</option>
          <option value="all">全部反馈</option>
        </select>
      </div>
      <label className="flex flex-col gap-2 text-13">
        关联原始反馈 *
        <select
          className={`${fieldClass} w-full min-w-0 truncate`}
          title={feedback?.results.find((item) => item.id === defectId)?.title}
          value={defectId}
          required
          disabled={busy || !feedback}
          onChange={(event) => {
            setDefectId(event.target.value);
            setHistoryPage(1);
            setRun(null);
            setError("");
          }}
        >
          <option value="">请选择原始反馈</option>
          {feedback?.results.map((item) => (
            <option key={item.id} value={item.id}>
              {item.code}
              {item.latest_status
                ? ` · ${{ pending: "待处理", running: "处理中", repaired: "已修复", verified: "验证正常", unresolved: "需跟进" }[item.latest_status] || "待确认"}`
                : ""}
              {item.run_count ? ` · ${item.run_count} 轮` : ""} ·{" "}
              {item.title.length > 64 ? `${item.title.slice(0, 64)}…` : item.title}
            </option>
          ))}
        </select>
      </label>
      {feedback && (feedback.count || 0) > 20 && (
        <div className="flex items-center gap-3 text-12 text-secondary">
          <button
            type="button"
            disabled={busy || page === 1}
            onClick={() => {
              setPage(page - 1);
              setDefectId("");
            }}
          >
            上一页
          </button>
          <span>
            第 {page} 页 · 共 {feedback.count} 条
          </span>
          <button
            type="button"
            disabled={busy || page * 20 >= feedback.count}
            onClick={() => {
              setPage(page + 1);
              setDefectId("");
            }}
          >
            下一页
          </button>
        </div>
      )}
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
      {feedback && !feedback.results.length && (
        <p role="status" className="text-13 text-secondary">
          当前筛选没有匹配反馈；可搜索编号或切换“全部反馈”。
        </p>
      )}
      {feedbackError && (
        <p role="alert" className="text-13 text-danger-primary">
          无法读取原始反馈：{errorMessage(feedbackError)}
        </p>
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
              {agentStatusLabel(run.status)}
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
