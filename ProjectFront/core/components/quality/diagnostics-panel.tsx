import { v4 as uuidv4 } from "uuid";
import { Paging, Badge } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { can, severityNames } from "./types";
import { AssistantMarkdown } from "@/components/knowledge/assistant-markdown";
import { DeploymentSnapshots } from "./deployment-snapshots";
import { FileText, ChevronRight, RotateCw, CircleCheck, Download } from "lucide-react";
import type { Context } from "./types";
type FailureMetadata = {
  source?: string;
  transport_phase?: string;
  deadline_kind?: string;
  provider_called?: boolean;
};
type AttemptFailure = FailureMetadata & { attempt: number; code: string; duration_ms: number };

function knownFailureLabel(labels: Record<string, string>, value = "") {
  return Object.hasOwn(labels, value) ? labels[value] : undefined;
}

function failureLabel(value: FailureMetadata, timeout: boolean) {
  if (value.source === "pre_model_materials") return timeout ? "材料读取超时" : "材料读取失败";
  const phase = knownFailureLabel(
    { connect: "连接", read: "响应", write: "发送请求", pool: "连接池等待" },
    value.transport_phase
  );
  if (phase) return `${phase}${timeout ? "超时" : "失败"}`;
  const deadline = knownFailureLabel(
    {
      request_timeout: "单次请求超时",
      first_event_timeout: "首个响应超时",
      agent_run: "分析执行超时",
      subprocess_deadline: "诊断进程超时",
      pre_model_materials: "材料读取超时",
    },
    value.deadline_kind
  );
  return deadline || "原因未知";
}

function failureSource(value: FailureMetadata) {
  return (
    knownFailureLabel(
      {
        agent_transport: "模型接口",
        agent_deadline: "分析时限",
        subprocess_deadline: "诊断进程",
        pre_model_materials: "材料读取",
        direct_sdk: "模型接口",
      },
      value.source
    ) || "来源未知"
  );
}

function attemptLabel(value: AttemptFailure) {
  if (value.code === "AGENT_USAGE_LIMIT") return "调用预算耗尽";
  if (["AGENT_INVALID_OUTPUT", "INVALID_DIAGNOSTIC_OUTPUT", "INVALID_DIAGNOSTIC_CITATION"].includes(value.code))
    return "输出校验失败";
  if (value.code === "AGENT_PROVIDER_AUTH") return "模型认证失败";
  return failureLabel(value, value.code === "MODEL_TIMEOUT");
}

type Job = {
  id: string;
  status: string;
  mode: string;
  error_code: string;
  created_at: string;
  feedback?: "helpful" | "unhelpful" | "";
  feedback_note?: string;
  result: {
    severity_assessment?: {
      severity: string;
      basis: string;
      evidence: { reference: string; quote: string }[];
      method?: "model_verified" | "evidence_rules" | "pending";
    };
    assignment?: { module: { key: string; name: string } | null; assignee: string; origin: string; reason: string };
    method?: string;
    model_status?: string;
    model_error_code?: string;
    timeout_seconds?: number;
    retry?: { count: number; limit: number; next_at: string; last_error: string };
    model_failure?: FailureMetadata;
    attempt_failures?: AttemptFailure[];
    progress?: { stage: string; at: string };
    fallback?: string;
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
    material_coverage?: {
      file_id: string;
      name: string;
      kind: "text" | "image" | "archive" | "other";
      status: "analyzed" | "unsupported" | "not_read";
      reason: string;
      verified: boolean;
    }[];
    sources?: {
      file_id: string;
      name: string;
      archive_entry?: string;
      origin?: "image_ocr";
      requires_review?: boolean;
      original_bytes_scope?: string;
      text_bytes?: number;
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
  if (job.result.model_status === "materials_unsupported") return "需补文字说明";
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
      qualityApi.read<{
        results: Job[];
        count: number;
        current_report?: Job;
        latest_attempt?: Job;
        project_queue_position?: number;
      }>(url),
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
  const [showProgress, setShowProgress] = useState(false);
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
        {job.result.severity_assessment && (
          <details className="rounded-md border border-subtle bg-layer-1 px-3 py-2 text-12">
            <summary className="flex cursor-pointer items-center gap-2">
              <span>本次判级建议</span>
              <Badge
                value={job.result.severity_assessment.severity}
                label={severityNames[job.result.severity_assessment.severity] || "待评估"}
              />
              {job.result.severity_assessment.method && (
                <span className="rounded bg-surface-1 px-1.5 py-0.5 text-11 text-secondary">
                  {
                    { model_verified: "模型判级", evidence_rules: "材料规则判级", pending: "待评估" }[
                      job.result.severity_assessment.method
                    ]
                  }
                </span>
              )}
              <span className="text-11 text-secondary">判级依据</span>
            </summary>
            <p className="mt-2 break-words text-secondary">{job.result.severity_assessment.basis}</p>
            {job.result.severity_assessment.evidence?.map((item) => (
              <blockquote
                key={`${item.reference}:${item.quote}`}
                className="mt-2 border-l border-subtle pl-2 text-11 text-secondary"
              >
                <span className="break-all">{item.reference}</span>
                <p className="mt-1 break-words whitespace-pre-wrap">{item.quote}</p>
              </blockquote>
            ))}
          </details>
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
            {job.status === "queued" && job.result.retry
              ? `等待重试 · ${job.result.retry.count}/${job.result.retry.limit}`
              : job.status === "queued"
                ? data?.project_queue_position
                  ? `排队中 · 本项目第 ${data.project_queue_position} 条`
                  : "排队中，尚未开始分析"
                : "正在读取材料并分析"}
          </p>
        )}
        {job.result.fallback === "rules_after_retries" && (
          <p className="rounded-md bg-warning-subtle px-3 py-2 text-warning-primary">
            重试已结束，按规则处理 · 可手动重新诊断
          </p>
        )}
        {job.result.model_status && !["not_requested", "completed"].includes(job.result.model_status) && (
          <p className="rounded-md bg-layer-1 px-3 py-2 text-secondary">
            {(
              {
                unconfigured: "模型未配置 · 已保留规则结果",
                timeout: "模型分析超时 · 已保留规则结果",
                failed:
                  job.result.model_error_code === "AGENT_PROVIDER_AUTH"
                    ? "模型认证失败 · 已保留规则结果"
                    : job.result.model_error_code === "AGENT_PROVIDER_UNAVAILABLE"
                      ? "模型接口暂不可用 · 可重新分析"
                      : job.result.model_error_code === "AGENT_INVALID_OUTPUT"
                        ? "模型返回格式异常 · 可重新分析"
                        : "模型分析失败 · 已保留规则结果",
                materials_unsupported: "附件已保存；暂无可用于诊断的文字，请补充文字或日志。",
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
            <span>
              {job.result.material_coverage?.length
                ? `附件 ${job.result.material_coverage.length} · 已读取 ${job.result.material_coverage.filter((file) => file.status === "analyzed").length}`
                : `${job.result.sources?.length || 0} 份材料`}
            </span>
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
        {(!!job.result.material_coverage?.length || !!job.result.sources?.length) && (
          <details open className="space-y-2 rounded-md border border-subtle p-3">
            <summary className="cursor-pointer font-medium">
              {job.result.material_coverage?.length
                ? `诊断材料（${job.result.material_coverage.length}）`
                : `已读取材料（${job.result.sources?.length}）`}
            </summary>
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
            {job.result.material_coverage?.map((file) => (
              <div
                key={file.file_id}
                className="flex min-w-0 flex-wrap items-center gap-2 rounded-md bg-layer-1 px-3 py-2 text-11"
              >
                <span className="min-w-0 flex-1 break-all">{file.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 ${file.verified ? "bg-success-subtle text-success-primary" : "bg-layer-1 text-secondary"}`}
                >
                  {file.verified ? "已校验" : "未校验"}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 ${file.status === "analyzed" ? "bg-accent-subtle text-accent-primary" : file.status === "unsupported" ? "bg-warning-subtle text-warning-primary" : "bg-layer-1 text-secondary"}`}
                >
                  {file.status === "analyzed" ? "已读取" : file.status === "unsupported" ? "未分析" : "未读取"}
                </span>
                <a className="shrink-0 text-accent-primary" href={`${base}files/${file.file_id}/download/`} download>
                  下载
                </a>
                {file.reason && <p className="w-full break-words text-secondary">{file.reason}</p>}
              </div>
            ))}
            {job.result.sources?.map((source) => (
              <div
                key={`${source.file_id}:${source.archive_entry || source.name}`}
                className="flex min-w-0 flex-wrap items-center gap-2 rounded-md bg-layer-1 px-3 py-2"
              >
                <FileText className="size-3.5 shrink-0 text-secondary" />
                <span className="min-w-0 flex-1 text-11 break-all">
                  {[source.name, source.archive_entry].filter(Boolean).join(" / ")}
                </span>
                {source.origin === "image_ocr" && (
                  <span className="rounded-full bg-warning-subtle px-2 py-0.5 text-11 text-warning-primary">
                    图片文字·需核对原图
                  </span>
                )}
                <span className="text-11 text-secondary">
                  {source.origin === "image_ocr"
                    ? `识别文字 ${source.text_bytes ?? source.read_bytes} 字节${source.file_bytes !== undefined ? ` · 原图 ${source.file_bytes} 字节` : ""}`
                    : `已读取 ${source.read_bytes} 字节${source.file_bytes !== undefined ? ` / 文件 ${source.file_bytes} 字节` : ""}`}
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
            {row.title}
          </p>
        ))}
        {!!job.result.context_references?.length && (
          <details className="space-y-2 text-12">
            <summary className="cursor-pointer text-secondary">
              平台记录与历史评价（{job.result.context_references.length}）
            </summary>
            <p className="text-11 text-secondary">平台记录显示接收和验收情况；历史评价需结合本次证据复核。</p>
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
  const progressJob = data?.latest_attempt || currentReport;
  const attemptFailures = (progressJob?.result.attempt_failures || [])
    .filter(
      (row, index, rows) =>
        Number.isInteger(row.attempt) &&
        row.attempt >= 1 &&
        row.attempt <= 4 &&
        rows.findIndex((candidate) => candidate.attempt === row.attempt) === index
    )
    .slice(0, 4);
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
      {progressJob && (
        <div className="text-12">
          <button
            type="button"
            aria-expanded={showProgress}
            onClick={() => setShowProgress(!showProgress)}
            className="inline-flex items-center gap-1 rounded-md border border-subtle px-2 py-1 text-accent-primary hover:bg-layer-1"
          >
            <RotateCw className="size-3" />
            诊断进度
          </button>
          {showProgress && (
            <div
              role="status"
              className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-subtle bg-layer-1 px-3 py-2 text-secondary"
            >
              <span>
                {data?.latest_attempt?.status === "queued"
                  ? data.latest_attempt.result.retry
                    ? `等待重试 ${data.latest_attempt.result.retry.count}/${data.latest_attempt.result.retry.limit}`
                    : `排队中${data.project_queue_position ? ` · 本项目第 ${data.project_queue_position} 条` : ""}`
                  : progressJob.status === "running"
                    ? progressJob.result.progress?.stage === "model_analysis"
                      ? "模型分析中"
                      : "读取材料与规则检查"
                    : progressJob.result.model_status === "completed"
                      ? "报告已生成"
                      : progressJob.result.model_status === "timeout"
                        ? "分析超时"
                        : progressJob.result.model_status === "failed"
                          ? "模型分析失败"
                          : progressJob.result.model_status === "materials_unsupported"
                            ? "需补文字说明"
                            : names[progressJob.status]}
              </span>
              {progressJob.result.material_coverage?.length ? (
                <span>
                  附件 {progressJob.result.material_coverage.length} · 已读取{" "}
                  {progressJob.result.material_coverage.filter((file) => file.status === "analyzed").length}
                </span>
              ) : (
                !!progressJob.result.sources?.length && <span>已读取 {progressJob.result.sources.length} 份材料</span>
              )}
              {progressJob.result.timeout_seconds && <span>分析时限 {progressJob.result.timeout_seconds} 秒</span>}
              {progressJob.result.model_failure && (
                <p className="w-full">
                  本次：{failureLabel(progressJob.result.model_failure, progressJob.result.model_status === "timeout")}
                  {" · "}
                  {failureSource(progressJob.result.model_failure)}
                  {progressJob.result.model_failure.provider_called === false && " · 未调用模型接口"}
                </p>
              )}
              {attemptFailures.length > 0 && (
                <div className="w-full space-y-1">
                  <p>此前尝试</p>
                  <ul className="space-y-1">
                    {attemptFailures.map((failure) => (
                      <li key={failure.attempt}>
                        第{failure.attempt}次 · {attemptLabel(failure)} · {failureSource(failure)}
                        {Number.isFinite(failure.duration_ms) &&
                        failure.duration_ms >= 0 &&
                        failure.duration_ms <= 86400000
                          ? ` · ${(failure.duration_ms / 1000).toFixed(1)} 秒`
                          : ""}
                        {failure.provider_called === false && " · 未调用模型接口"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
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
