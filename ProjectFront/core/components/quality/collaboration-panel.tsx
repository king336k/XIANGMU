import { sortBy } from "lodash-es";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { can, statusNames, resultNames } from "./types";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";
import { AttachmentUpload } from "./attachment-upload";
import { PackageForm } from "./package-form";
import type { Context, Defect } from "./types";

type Source = {
  id: string;
  source_system: string;
  source_instance: string;
  record_type: string;
  record_id: string;
  task_id: string;
  package_id: string;
  device: string;
  source_context?: {
    platformProjectId?: number;
    reporter?: { id: number; username: string };
    platformProjectName: string;
    platformTaskId: number | null;
    platformTaskName: string;
    sourceReference: string;
  } | null;
};

export function SourceCard({ source }: { source: Source }) {
  const context = source.source_context;
  return (
    <div className="space-y-1 rounded-md border border-subtle p-3 text-12 break-words">
      {context ? (
        <>
          <p>DAQ · {source.source_instance}</p>
          {context.reporter && <p className="text-secondary">采集员：{context.reporter.username}</p>}
          {context.sourceReference && (
            <p className="text-secondary">数据包 / Session 上报引用：{context.sourceReference}</p>
          )}
          {source.device && <p className="text-secondary">设备：{source.device}</p>}
        </>
      ) : (
        <>
          <p>
            {source.source_system} / {source.source_instance} · {source.record_type} · {source.record_id}
          </p>
          <p className="text-secondary">
            设备：{source.device || "未关联"} · 任务：{source.task_id || "未关联"} · 数据包：
            {source.package_id || "未关联"}
          </p>
        </>
      )}
    </div>
  );
}
type Comment = { id: string; content: string; visibility: "public" | "internal"; actor: string; created_at: string };
type CollaborationAccess = {
  can_remind: boolean;
  can_internal_comment: boolean;
  can_public_comment: boolean;
  cooldown_seconds: number;
};
type Package = {
  id: string;
  name: string;
  external_id: string;
  source_system: string;
  files: { path: string; size: number; sha256: string }[];
};

export function CollaborationPanel({
  base,
  value,
  context,
  onChanged,
}: {
  base: string;
  value: Defect;
  context: Context;
  onChanged: (defect: Defect) => Promise<void>;
}) {
  const url = `${base}defects/${value.id}/collaboration/`;
  const {
    data: comments,
    error: commentsError,
    mutate: refreshComments,
  } = useSWR(url, () => qualityApi.all<Comment>(url));
  const { data: sources, error: sourcesError } = useSWR(`${base}defects/${value.id}/sources/`, (key: string) =>
    qualityApi.read<Source[]>(key)
  );
  const packageUrl = `${base}packages/?defect_id=${value.id}`;
  const {
    data: packages,
    error: packagesError,
    mutate: refreshPackages,
  } = useSWR(packageUrl, () => qualityApi.read<{ results: Package[]; count: number }>(packageUrl));
  const [content, setContent] = useState("");
  const [visibility, setVisibility] = useState<"public" | "internal">("public");
  const [reminderTarget, setReminderTarget] = useState("assignee");
  const { data: access } = useSWR(`${base}defects/${value.id}/reminders/`, (key: string) =>
    qualityApi.read<CollaborationAccess>(key)
  );
  const [addingPackage, setAddingPackage] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const failed = commentsError || sourcesError || packagesError;
  const timeline = sortBy(
    [
      ...(value.events || []).map((event) => {
        const rawNote = event.note?.trim() || "";
        const note = rawNote
          .replace(/^(.*验证第\d+轮)[：:]\s*$/, "$1")
          .replace(
            /^(记录人工实测.*|执行用例.*)[：:]\s*(passed|failed|blocked|inconclusive|skipped)$/,
            (_, action, result: string) => `${action}：${resultNames[result] || result}`
          );
        const specific = note.match(
          /^(初步分派|诊断自动指派|人工改派|验证安排|验证方式|人工验证关闭|人工验证安排|记录人工实测|执行用例|补充回归用例|更新人工验证要求|更新本轮测试要求|调整测试负责人|指派测试员|接收交接|拒绝交接|取消待确认交接|补充上报信息|提交验证结果|提交验证|经理验收通过|验收关闭|退回复测|退回补测|退回修复|重新打开|重开)(?=第\d+轮|[：，；（]|$)/
        )?.[1];
        const daqCreated = !event.previous_status && value.source_kind === "daq";
        const changed = event.previous_status !== event.status;
        const unsuccessful =
          /^(退回|拒绝|重开)/.test(note) ||
          /^(记录人工实测|执行用例).*[：:]\s*(failed|blocked|失败|阻塞|受阻)$/.test(note) ||
          (event.status === "open" && ["resolved", "closed"].includes(event.previous_status));
        const passed =
          !unsuccessful &&
          (event.status === "closed" || /验证通过|验收通过|^验收关闭|^(记录人工实测|执行用例).*：通过$/.test(note));
        return {
          id: `event-${event.id}`,
          actor: daqCreated ? "" : event.actor || "成员",
          at: event.created_at,
          action: daqCreated
            ? "DAQ异常反馈上报"
            : changed
              ? event.previous_status
                ? `${statusNames[event.previous_status] || event.previous_status} → ${statusNames[event.status] || event.status}`
                : "提交缺陷"
              : specific || "更新缺陷",
          content: daqCreated
            ? `采集员：${value.reporter?.username || value.created_by_name || "未记录"}\n问题：${value.title}`
            : !changed && specific && note.startsWith(`${specific}：`)
              ? note.slice(specific.length + 1).trim()
              : note === "更新缺陷"
                ? ""
                : note,
          tone: unsuccessful
            ? "text-danger-primary"
            : passed
              ? "text-success-primary"
              : note.startsWith("提交验证")
                ? "text-warning-primary"
                : changed && event.status === "open"
                  ? "text-secondary"
                  : "text-accent-primary",
        };
      }),
      ...(comments || []).map((comment) => ({
        id: `comment-${comment.id}`,
        actor: comment.actor,
        at: comment.created_at,
        action: comment.visibility === "internal" ? "内部备注" : "采集员可见回复",
        tone: "text-secondary",
        content: comment.content,
      })),
    ],
    (entry) => new Date(entry.at).getTime()
  );
  const days = new Map<string, typeof timeline>();
  for (const row of timeline) {
    const date = renderNumericDateTime(row.at).slice(0, 10);
    days.set(date, [...(days.get(date) || []), row]);
  }
  const latestDay = [...days.keys()].at(-1);
  return (
    <section className="space-y-4">
      <details className="text-12">
        <summary className="cursor-pointer text-secondary">上报来源与 Session（{sources?.length || 0}）</summary>
        <div className="mt-2 space-y-2">
          {sources?.map((source) => (
            <SourceCard key={source.id} source={source} />
          ))}
          {sources?.length === 0 && <p className="text-12 text-secondary">平台内创建，无 DAQ 来源。</p>}
        </div>
      </details>
      {can(context, "claim_defect") &&
        (!value.assignee_id || value.assignee_id === context.user_id) &&
        ["open", "in_progress"].includes(value.status) && (
          <Button
            type="button"
            variant="neutral-primary"
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                const changed = await qualityApi.write<Defect>(url, { action: "claim" });
                await onChanged(changed);
                setMessage("已认领，可继续处理。");
              })
            }
          >
            认领处理
          </Button>
        )}
      <div className="space-y-3">
        <h4 className="text-13 font-medium">处理时间线</h4>
        {!comments && !commentsError && (
          <p role="status" className="text-12 text-secondary">
            正在加载记录…
          </p>
        )}
        {timeline.length === 0 && <p className="text-12 text-secondary">暂无处理记录。</p>}
        <div aria-label="按日期查看操作记录" className="space-y-2">
          {[...days].map(([date, rows]) => (
            <details key={date} open={date === latestDay} className="rounded-md border border-subtle">
              <summary className="cursor-pointer px-3 py-2 text-12 text-secondary">
                {date} · {rows.length} 条记录
              </summary>
              <ul aria-label="处理时间线" className="m-0 list-none space-y-3 px-3 pb-3">
                {rows.map((row) => (
                  <li key={row.id} className="m-0 list-none border-l-2 border-subtle pl-3 text-12">
                    <p className="m-0 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      <strong className="font-medium">{row.actor}</strong>
                      <span className={`font-medium ${row.tone}`}>{row.action}</span>
                      <time className="text-11 text-tertiary" dateTime={row.at}>
                        {renderNumericDateTime(row.at)}
                      </time>
                    </p>
                    {row.content &&
                      (row.content.length > 180 || row.content.split("\n").length > 3 ? (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-secondary">查看详细内容</summary>
                          <p className="mt-1 break-words whitespace-pre-wrap text-secondary">{row.content}</p>
                        </details>
                      ) : (
                        <p className="mt-1 break-words whitespace-pre-wrap text-secondary">{row.content}</p>
                      ))}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
        {(access?.can_public_comment || access?.can_internal_comment) && (
          <>
            <Field label="回复范围">
              <select
                className={fieldClass}
                value={visibility}
                onChange={(event) => setVisibility(event.target.value as "public" | "internal")}
              >
                {access.can_public_comment && <option value="public">采集员可见回复</option>}
                {access.can_internal_comment && <option value="internal">内部备注</option>}
              </select>
            </Field>
            <Field label={visibility === "internal" ? "添加内部备注" : "添加采集员可见回复"}>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={2}
                maxLength={10000}
                className={fieldClass}
              />
            </Field>
            <Button
              type="button"
              variant="neutral-primary"
              disabled={busy || !content.trim()}
              onClick={() =>
                void perform(async () => {
                  await qualityApi.write(url, { action: "comment", content, visibility });
                  await refreshComments();
                  setContent("");
                  setMessage("评论已保存。");
                })
              }
            >
              {visibility === "internal" ? "保存内部备注" : "发布回复"}
            </Button>
          </>
        )}
      </div>
      {access?.can_remind && (
        <details className="space-y-2 rounded-md border border-subtle p-3">
          <summary className="cursor-pointer text-13 font-medium">提醒处理人</summary>
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="催办职责"
              value={reminderTarget}
              onChange={(event) => setReminderTarget(event.target.value)}
              className={`${fieldClass} w-40`}
            >
              <option value="assignee">当前负责人</option>
              {value.pending_assignee_id && <option value="pending_assignee">待交接接收人</option>}
              {!!value.collaborators?.length && <option value="collaborators">协作者</option>}
              <option value="managers">项目经理</option>
            </select>
            <Button
              variant="neutral-primary"
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  const result = await qualityApi.write<{ sent: number; cooldown_seconds: number }>(
                    `${base}defects/${value.id}/reminders/`,
                    { target: reminderTarget }
                  );
                  setMessage(`已向${result.sent}位成员发送站内催办。`);
                })
              }
            >
              发送站内催办
            </Button>
          </div>
          <p className="text-12 text-secondary">
            同一缺陷对同一接收人10分钟内只提醒一次。只发送站内事件，不含评论正文。
          </p>
        </details>
      )}
      <details className="space-y-3 text-12">
        <summary className="cursor-pointer text-secondary">诊断材料清单与接入信息（高级）</summary>
        {packages?.count === 0 && <p className="text-12 text-secondary">暂无已登记清单。</p>}
        {packages?.results
          .filter((item) => item.source_system !== "MANUAL_ATTACHMENT")
          .map((item) => (
            <details key={item.id} className="rounded-md border border-subtle p-3 text-12">
              <summary className="cursor-pointer">
                {item.name} · {item.external_id} · 已登记清单（{item.files.length} 个文件）
              </summary>
              <ul className="mt-2 space-y-1 break-all">
                {item.files.map((file) => (
                  <li key={file.path}>
                    {file.path} · {file.size} 字节 · SHA256 {file.sha256}
                  </li>
                ))}
              </ul>
              <AttachmentUpload
                base={base}
                packageId={item.id}
                paths={item.files.map((file) => file.path)}
                canUpload={can(context, "package")}
              />
            </details>
          ))}
        <p className="text-12 text-secondary">
          先登记清单，再上传同名诊断文件；系统核对大小和SHA256，文件仅允许有项目权限的成员下载。
        </p>
        {can(context, "package") && (
          <Button type="button" variant="neutral-primary" onClick={() => setAddingPackage(true)}>
            登记问题包清单
          </Button>
        )}
        {addingPackage && (
          <PackageForm
            base={base}
            defectId={value.id}
            onClose={() => setAddingPackage(false)}
            onSaved={async () => {
              await refreshPackages();
            }}
          />
        )}
      </details>
      {(error || failed) && (
        <p role="alert" className="text-13 text-danger-primary">
          {error || errorMessage(failed)}
        </p>
      )}
      {message && (
        <p role="status" className="text-13 text-success-primary">
          {message}
        </p>
      )}
    </section>
  );
}
