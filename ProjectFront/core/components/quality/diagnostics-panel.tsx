import { v4 as uuidv4 } from "uuid";
import { Paging } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { can } from "./types";
import { AssistantMarkdown } from "@/components/knowledge/assistant-markdown";
import { DeploymentSnapshots } from "./deployment-snapshots";
import { FileText, ChevronRight, RotateCw, CircleCheck, Download } from "lucide-react";
import type { Context } from "./types";
type Job = {
  id: string;
  status: string;
  mode: string;
  error_code: string;
  created_at: string;
  feedback?: "helpful" | "unhelpful" | "";
  feedback_note?: string;
  result: {
    assignment?: { module: { key: string; name: string } | null; assignee: string; origin: string; reason: string };
    method?: string;
    model_status?: string;
    version?: number;
    trigger?: string;
    duration_ms?: number;
    materials_status?: string;
    read_bytes?: number;
    input_scope?: { model_text_chars: number; model_text_truncated: boolean };
    verification_steps?: string[];
    notice?: string;
    answer?: string;
    model_confidence?: number | null;
    evidence_assessment?: "supported" | "partial" | "insufficient" | null;
    confidence_basis?: string;
    confidence_references?: { reference: string; title: string }[];
    model_info?: { model?: string; engine?: string; instruction_version?: string };
    suggested_actions?: string[];
    findings?: {
      kind: string;
      title: string;
      samples: string[];
      basis?: string;
      recommendations?: string[];
      confidence?: number;
      confidence_source?: string;
    }[];
    sources?: {
      file_id: string;
      name: string;
      archive_entry?: string;
      excerpt?: string;
      read_bytes: number;
      scan_incomplete?: boolean;
      file_bytes?: number;
      preview_truncated?: boolean;
      truncated: boolean;
    }[];
    citations?: { reference: string; title: string }[];
    context_references?: { reference: string; title: string; content: string }[];
  };
};
const names: Record<string, string> = {
  queued: "等待执行",
  running: "诊断中",
  completed: "已生成报告",
  failed: "失败",
  cancelled: "已取消",
  unconfigured: "模型未配置",
  reference_unavailable: "引用已失效",
};
function reportLabel(job: Job) {
  if (job.result.model_status === "awaiting_materials") return "等待材料";
  if (
    job.status === "completed" &&
    ["failed", "timeout", "unconfigured", "reference_unavailable"].includes(job.result.model_status || "")
  )
    return "仅规则结果";
  return names[job.status] || job.status;
}
export function DiagnosticsPanel({
  base,
  defectId,
  context,
  onCompleted,
}: {
  base: string;
  defectId: string;
  context: Context;
  onCompleted?: () => Promise<unknown>;
}) {
  const pagination = useCollectionPagination(`${base}:diagnostics:${defectId}`);
  const { data, error, mutate, isLoading } = useSWR(
    `${base}defects/${defectId}/diagnostics/?${pagination.query}`,
    (url: string) =>
      qualityApi.read<{ results: Job[]; count: number; current_report?: Job; latest_attempt?: Job }>(url),
    { refreshInterval: (page) => (page?.results.some((row) => ["queued", "running"].includes(row.status)) ? 2000 : 0) }
  );
  const { data: modelStatus } = useSWR(`${base.replace("/quality/", "/knowledge/")}status/`, (url: string) =>
    qualityApi.read<{ configured: boolean }>(url)
  );
  const completed = data?.results.find((row) => row.status === "completed");
  const completedKey = completed ? `${defectId}:${completed.id}` : "";
  const lastCompleted = useRef("");
  useEffect(() => {
    if (!completedKey || !onCompleted || lastCompleted.current === completedKey) return;
    lastCompleted.current = completedKey;
    void onCompleted().catch(() => {
      lastCompleted.current = "";
    });
  }, [completedKey, onCompleted]);
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const [feedbackNotes, setFeedbackNotes] = useState<Record<string, string>>({});
  const [feedbackChoices, setFeedbackChoices] = useState<Record<string, string>>({});
  const saveFeedback = async (job: Job, choice: string) => {
    setBusy(true);
    setMessage("");
    try {
      await qualityApi.write(`${base}diagnostics/${job.id}/`, {
        action: "feedback",
        feedback: choice,
        note: feedbackNotes[job.id] ?? job.feedback_note ?? "",
      });
      setFeedbackChoices((values) => ({ ...values, [job.id]: choice }));
      setMessage("评价已保存，后续相关诊断会参考这条反馈；评价不会替代现场证据。");
      await mutate();
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  const start = async (mode: string) => {
    setBusy(true);
    setMessage("");
    try {
      await qualityApi.write(`${base}defects/${defectId}/diagnostics/`, { request_id: uuidv4(), mode });
      await mutate();
    } catch (e) {
      setMessage(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const downloadAttachments = async () => {
    setBusy(true);
    setMessage("");
    try {
      await qualityApi.download(
        `${base}defects/${encodeURIComponent(defectId)}/attachments/download/`,
        `${defectId.replace(/[^a-zA-Z0-9_-]/g, "_")}-附件.zip`
      );
    } catch (e) {
      setMessage(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const renderReport = (job: Job, current = false) => (
    <details key={job.id} open={current} className="group/diagnostic min-w-0 rounded-md border border-subtle text-12">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 p-3">
        <ChevronRight className="size-3.5 text-tertiary transition-transform group-open/diagnostic:rotate-90" />
        <span className="font-medium">
          {current ? "当前报告" : "报告"} {job.result.version ? `v${job.result.version}` : ""}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-11 ${job.status === "completed" && reportLabel(job) === "已生成报告" ? "bg-success-subtle text-success-primary" : job.status === "failed" ? "bg-danger-subtle text-danger-primary" : "bg-layer-1 text-secondary"}`}
        >
          {reportLabel(job)}
        </span>
        <span className="ml-auto text-11 text-secondary">{renderNumericDateTime(job.created_at)}</span>
      </summary>
      <div className="space-y-4 border-t border-subtle p-3">
        {job.result.assignment && (
          <div className="rounded-md border border-subtle bg-layer-1 px-3 py-2 text-12">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-accent-subtle px-2 py-1 text-accent-primary">
                {job.result.assignment.module?.name || "模块待确认"}
              </span>
              <span className="font-medium">{job.result.assignment.assignee || "待指派"}</span>
              <span className="text-secondary">
                {(
                  { diagnostic: "诊断指派", manual: "保留人工指派", initial: "初分", triage: "待分诊" } as Record<
                    string,
                    string
                  >
                )[job.result.assignment.origin] || "待确认"}
              </span>
            </div>
            {job.result.assignment.reason && (
              <details className="mt-2">
                <summary className="cursor-pointer text-accent-primary">指派依据</summary>
                <p className="mt-2 break-words text-secondary">{job.result.assignment.reason}</p>
              </details>
            )}
          </div>
        )}
        {["queued", "running"].includes(job.status) && can(context, "manage_defect") && (
          <Button
            type="button"
            variant="neutral-primary"
            onClick={async () => {
              try {
                await qualityApi.write(`${base}diagnostics/${job.id}/`, { action: "cancel" });
                await mutate();
              } catch (e) {
                setMessage(errorMessage(e));
              }
            }}
          >
            取消任务
          </Button>
        )}
        {job.status === "unconfigured" && <p className="text-secondary">模型未配置。</p>}
        {["queued", "running"].includes(job.status) && (
          <p role="status" className="flex items-center gap-2 text-secondary">
            <RotateCw className="size-3.5 animate-spin motion-reduce:animate-none" />
            {job.status === "queued" ? "排队中，尚未开始分析" : "正在读取材料并分析"}
          </p>
        )}
        {job.result.model_status && !["not_requested", "completed"].includes(job.result.model_status) && (
          <p className="rounded-md bg-layer-1 px-3 py-2 text-secondary">
            {(
              {
                unconfigured: "模型未配置 · 已保留规则结果",
                timeout: "模型分析超时 · 已保留规则结果",
                failed: "模型分析失败 · 已保留规则结果",
                awaiting_materials: "等待日志上传完成，随后自动诊断",
                reference_unavailable: "知识引用已失效 · 显示规则结果",
              } as Record<string, string>
            )[job.result.model_status] || "显示规则结果"}
          </p>
        )}
        {job.result.materials_status === "awaiting_materials" && (
          <p className="text-secondary">尚未读取到日志；当前仅分析上报描述。</p>
        )}
        {job.error_code && (
          <p className="text-secondary">
            {job.error_code === "QUEUE_WAIT_TIMEOUT"
              ? "排队等待过久，请稍后重试。"
              : job.error_code === "DIAGNOSTIC_TIMEOUT"
                ? "诊断执行超时，可重新发起。"
                : job.error_code === "NO_PUBLISHED_KNOWLEDGE"
                  ? "没有可引用的已发布知识，请先补充知识库。"
                  : job.error_code === "QUEUE_UNAVAILABLE"
                    ? "后台队列暂不可用，请稍后重新发起。"
                    : "任务未完成或引用已失效，请核对来源后重新发起。"}
          </p>
        )}
        {job.status === "completed" && (
          <div className="flex flex-wrap items-center gap-3 text-11 text-secondary">
            <span className="flex items-center gap-1">
              <CircleCheck className="size-3.5" />
              {job.result.method === "hybrid" ? "规则与模型" : "规则检查"}
            </span>
            <span>{job.result.sources?.length || 0} 份材料</span>
            {job.result.duration_ms !== undefined && <span>执行 {(job.result.duration_ms / 1000).toFixed(1)} 秒</span>}
            {job.result.trigger && <span>{job.result.trigger === "manual" ? "手动发起" : "自动初诊"}</span>}
          </div>
        )}
        {job.result.answer && (
          <div className="max-h-80 overflow-y-auto rounded-md bg-layer-1 p-3 text-13 leading-6">
            <AssistantMarkdown content={job.result.answer} />
          </div>
        )}
        {job.result.model_status === "completed" &&
          typeof job.result.model_confidence === "number" &&
          Number.isFinite(job.result.model_confidence) &&
          job.result.model_confidence >= 0 &&
          job.result.model_confidence <= 1 && (
            <div className="space-y-1 rounded-md border border-subtle px-3 py-2 text-12">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-11 text-accent-primary">
                  模型自评 {Math.round(job.result.model_confidence * 100)}%
                </span>
                <span className="text-secondary">
                  {job.result.evidence_assessment === "supported"
                    ? "材料支持当前判断"
                    : job.result.evidence_assessment === "partial"
                      ? "材料部分支持"
                      : "材料不足"}{" "}
                  · 非正确概率
                </span>
              </div>
              {job.result.confidence_basis && <p className="leading-6 text-secondary">{job.result.confidence_basis}</p>}
            </div>
          )}
        {job.result.model_info?.model && (
          <details className="text-11 text-secondary">
            <summary className="cursor-pointer">分析来源</summary>
            <p className="mt-1 break-all">
              {job.result.model_info.engine || "模型"} · {job.result.model_info.model}
            </p>
            {job.result.model_info.instruction_version && (
              <p className="mt-1">报告格式 {job.result.model_info.instruction_version}</p>
            )}
          </details>
        )}
        {!!job.result.findings?.length && (
          <details className="rounded-md border border-subtle p-3">
            <summary className="cursor-pointer font-medium">规则发现（{job.result.findings.length}）</summary>
            <div className="mt-3 space-y-3">
              {job.result.findings.map((row) => (
                <div key={row.kind}>
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="font-medium">{row.title}</h4>
                    {row.confidence_source === "rule" &&
                      typeof row.confidence === "number" &&
                      Number.isFinite(row.confidence) &&
                      row.confidence >= 0 &&
                      row.confidence <= 1 && (
                        <span
                          className="rounded-full bg-accent-subtle px-2 py-0.5 text-11 text-accent-primary"
                          title="来源：诊断规则参数，需结合现场证据核实"
                        >
                          规则分值{Math.round(row.confidence * 100)}%
                        </span>
                      )}
                  </div>
                  {row.basis && <p className="mt-1 text-11 text-secondary">{row.basis}</p>}
                  <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-layer-1 p-3 text-11 leading-5">
                    <code>{row.samples.join("\n")}</code>
                  </pre>
                </div>
              ))}
            </div>
          </details>
        )}
        {job.result.method === "rules" && !job.result.findings?.length && (
          <p className="text-secondary">已读取范围内未发现匹配项。</p>
        )}
        {job.result.suggested_actions?.length ? (
          <details className="space-y-2 rounded-md border border-subtle p-3">
            <summary className="cursor-pointer font-medium">建议排查</summary>
            <ol className="list-decimal space-y-1 pl-5 text-secondary">
              {job.result.suggested_actions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </details>
        ) : null}
        {job.result.verification_steps?.length ? (
          <details className="space-y-2 rounded-md border border-subtle p-3">
            <summary className="cursor-pointer font-medium">验证方法</summary>
            <ol className="list-decimal space-y-1 pl-5 text-secondary">
              {job.result.verification_steps.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </details>
        ) : null}
        {!!job.result.sources?.length && (
          <details open className="space-y-2 rounded-md border border-subtle p-3">
            <summary className="cursor-pointer font-medium">已读取材料（{job.result.sources.length}）</summary>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button
                type="button"
                variant="neutral-primary"
                size="sm"
                aria-label="一键打包下载"
                title="下载此缺陷全部原附件"
                disabled={busy}
                onClick={() => void downloadAttachments()}
              >
                <Download className="mr-1 size-3.5" />
                一键打包下载
              </Button>
            </div>
            {job.result.sources.map((source) => (
              <div
                key={`${source.file_id}:${source.archive_entry || source.name}`}
                className="flex min-w-0 flex-wrap items-center gap-2 rounded-md bg-layer-1 px-3 py-2"
              >
                <FileText className="size-3.5 shrink-0 text-secondary" />
                <span className="min-w-0 flex-1 text-11 break-all">{source.archive_entry || source.name}</span>
                <span className="text-11 text-secondary">
                  已读取 {source.read_bytes} 字节
                  {source.file_bytes !== undefined ? ` / 文件 ${source.file_bytes} 字节` : ""}
                  {source.truncated ? " · 部分读取" : ""}
                </span>
                <a
                  className="shrink-0 text-11 text-accent-primary"
                  href={`${base}files/${source.file_id}/download/`}
                  download
                >
                  下载{source.archive_entry ? "原包" : ""}
                </a>
                {source.excerpt && (
                  <details className="w-full text-11">
                    <summary className="cursor-pointer text-accent-primary">
                      查看读取内容{source.preview_truncated ? "（预览摘录）" : ""}
                    </summary>
                    <pre className="mt-2 max-h-56 overflow-auto rounded border border-subtle bg-surface-1 p-3 leading-5">
                      <code>{source.excerpt}</code>
                    </pre>
                  </details>
                )}
              </div>
            ))}
          </details>
        )}
        {job.result.input_scope?.model_text_truncated && (
          <p className="text-11 text-secondary">模型分析使用了材料摘要，未覆盖全部正文。</p>
        )}
        {job.result.citations?.map((row) => (
          <p key={row.reference} className="text-secondary">
            参考：
            {job.result.sources?.find(
              (source) => source.archive_entry && row.reference.endsWith(`:${source.archive_entry}`)
            )?.archive_entry || row.title}
          </p>
        ))}
        {!!job.result.context_references?.length && (
          <details className="space-y-2 text-12">
            <summary className="cursor-pointer text-secondary">
              平台回执与历史评价参考（{job.result.context_references.length}）
            </summary>
            <p className="text-11 text-secondary">回执证明平台接收情况；历史评价是待复核建议，不替代本次现场证据。</p>
            {job.result.context_references.map((row) => (
              <div key={row.reference} className="rounded-md bg-layer-1 p-3">
                <p className="font-medium">{row.title}</p>
                <p className="mt-1 break-words whitespace-pre-wrap text-secondary">{row.content}</p>
              </div>
            ))}
          </details>
        )}
        {job.status === "completed" && (
          <div className="space-y-2 border-t border-subtle pt-3">
            <p className="text-12 text-secondary">评价这次诊断。补充误判位置和实际结果，可供后续相关诊断参考。</p>
            <textarea
              aria-label="诊断改进说明"
              rows={2}
              maxLength={2000}
              className="w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-12"
              placeholder="例如：本次是正常验收；平台已收到附件，不应再提示缺少接收回执。"
              value={feedbackNotes[job.id] ?? job.feedback_note ?? ""}
              onChange={(event) => setFeedbackNotes((values) => ({ ...values, [job.id]: event.target.value }))}
            />
            <div className="flex items-center gap-3">
              {[
                { key: "helpful", text: "有帮助" },
                { key: "unhelpful", text: "需改进" },
              ].map((option) => (
                <button
                  type="button"
                  key={option.key}
                  disabled={busy}
                  aria-pressed={(feedbackChoices[job.id] ?? job.feedback) === option.key}
                  className={`rounded px-2 py-1 text-12 disabled:opacity-50 ${(feedbackChoices[job.id] ?? job.feedback) === option.key ? "bg-accent-subtle font-medium text-accent-primary" : "text-secondary hover:bg-layer-1"}`}
                  onClick={() => void saveFeedback(job, option.key)}
                >
                  {option.text}
                </button>
              ))}
              {(feedbackChoices[job.id] ?? job.feedback) && (
                <span role="status" className="text-12 text-secondary">
                  已反馈：{(feedbackChoices[job.id] ?? job.feedback) === "helpful" ? "有帮助" : "需改进"}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </details>
  );
  const currentReport = data?.current_report || data?.results[0];
  const reportFileIds =
    currentReport?.result.sources
      ?.filter(
        (source) => source.scan_incomplete !== true && Number.isFinite(source.read_bytes) && source.read_bytes > 0
      )
      .map((source) => source.file_id) || [];
  const history = data?.results.filter((row) => row.id !== currentReport?.id) || [];
  return (
    <section aria-label="诊断报告" className="min-w-0 space-y-4 rounded-lg border border-subtle bg-surface-1 p-4">
      <DeploymentSnapshots base={base} defectId={defectId} compact reportFileIds={reportFileIds} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-13 font-medium">诊断报告</h3>
        {can(context, "manage_defect") && (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="neutral-primary" disabled={busy} onClick={() => void start("rules")}>
              检查材料
            </Button>
            <Button
              type="button"
              variant="neutral-primary"
              disabled={busy || !modelStatus?.configured}
              onClick={() => void start("auto")}
            >
              {!modelStatus ? "读取模型配置…" : modelStatus.configured ? "重新诊断" : "重新诊断（模型未配置）"}
            </Button>
          </div>
        )}
      </div>
      {(error || message) && (
        <p role="alert" className="text-12 text-danger-primary">
          {message || errorMessage(error)}
        </p>
      )}
      {isLoading && (
        <p role="status" className="text-12 text-secondary">
          正在读取诊断记录…
        </p>
      )}
      {data && !data.results.length && (
        <p className="text-12 text-secondary">上传日志或诊断包后自动分析；没有材料可直接分派处理。</p>
      )}
      {data?.latest_attempt && data.latest_attempt.id !== currentReport?.id && (
        <p role="status" className="rounded-md bg-layer-1 px-3 py-2 text-12 text-secondary">
          最新一次
          {data.latest_attempt.status === "running"
            ? "正在诊断"
            : data.latest_attempt.status === "queued"
              ? "等待执行"
              : "未生成新的模型结论"}
          ，当前显示同一材料的最近成功报告。
        </p>
      )}
      {currentReport && renderReport(currentReport, true)}
      {data && data.count > 1 && (
        <details className="rounded-md border border-subtle p-3 text-12">
          <summary className="cursor-pointer text-secondary">历史报告（{data.count - 1}）</summary>
          <div className="mt-3 space-y-3">{history.map((job) => renderReport(job))}</div>
          {data.count > pagination.perPage && <Paging {...pagination.paging} count={data.count} />}
        </details>
      )}
    </section>
  );
}
