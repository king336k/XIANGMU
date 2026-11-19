import { PagedRecordSelect } from "./paged-record-select";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import useSWR from "swr";

import { qualityApi } from "./api";
import { Badge, Field, fieldClass, Modal } from "./shared";
import { severityNames, statusNames, can } from "./types";
import { DefectDetail } from "./defect-detail";
import { uploadDefectFiles } from "./defect-attachments";
import type { Context, Defect, Execution, TestCase } from "./types";
import { DefectQuickEdit } from "./defect-quick-edit";
import { DefectDispositionPanel } from "./defect-disposition";
import { projectMembersPath } from "@/components/settings/management-paths";

export function DefectForm({
  base,
  context,
  value: initialValue,
  onClose,
  onSaved,
  projectUrl,
  onFromSource,
  initialMode,
  defaultBuild,
}: {
  defaultBuild?: string;
  base: string;
  context: Context;
  value?: Defect;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
  projectUrl: string;
  onFromSource?: () => void;
  initialMode?: "details" | "workflow";
}) {
  const [current, setCurrent] = useState(initialValue);
  const value = current ?? initialValue;
  const [editing, setEditing] = useState<"details" | "workflow" | "create" | null>(
    value ? (initialMode ?? null) : "create"
  );
  useSWR(current && !editing ? `${base}defects/${current.id}/` : null, (url: string) => qualityApi.read<Defect>(url), {
    refreshInterval: (snapshot) =>
      ["queued", "analysis", "inspect", "repair", "verify"].includes(snapshot?.agent_processing?.state || "")
        ? 5000
        : 0,
    refreshWhenHidden: false,
    onSuccess: (snapshot) => {
      if (snapshot.id === current?.id && !editing) setCurrent(snapshot);
    },
  });
  const persistedId = useRef<string | undefined>(value?.id);
  const [files, setFiles] = useState<File[]>([]);
  const [caseId, setCaseId] = useState(value?.case_id ?? "");
  const [status, setStatus] = useState(
    value?.status === "closed" && initialMode === "workflow" ? "open" : (value?.status ?? "open")
  );
  const [verificationMethod, setVerificationMethod] = useState("regression");
  const transitions: Record<string, string[]> = {
    open: ["open", "in_progress", "needs_tech", "pending_tech", "resolved"],
    pending_tech: ["pending_tech", "needs_tech", "in_progress", "resolved"],
    needs_tech: ["needs_tech", "pending_tech", "in_progress", "resolved"],
    in_progress: ["open", "in_progress", "needs_tech", "pending_tech", "resolved"],
    resolved: ["resolved", "open"],
    closed: ["closed", "open"],
  };
  const [editingAssignee, setEditingAssignee] = useState(false);
  const [assigneeId, setAssigneeId] = useState(value?.assignee_id ?? "");
  const { data: cases } = useSWR(`${base}cases/all`, () => qualityApi.all<TestCase>(`${base}cases/`));
  const { data: executions } = useSWR(value?.status === "resolved" ? `${base}executions/all` : null, () =>
    qualityApi.all<Execution>(`${base}executions/`)
  );
  const candidates = executions?.filter(
    (e) =>
      e.result === "passed" &&
      e.case_id === value?.case_id &&
      e.build === value?.fixed_build &&
      !!value?.resolved_at &&
      new Date(e.created_at) > new Date(value.resolved_at)
  );
  const detail = current ? (
    <DefectDetail
      base={base}
      value={current}
      context={context}
      projectUrl={projectUrl}
      onClose={onClose}
      onEdit={(mode) => {
        if (mode === "workflow") setStatus(current.status === "closed" ? "open" : current.status);
        setEditing(mode);
      }}
      onChanged={async (changed) => {
        setCurrent(changed);
        setAssigneeId(changed.assignee_id || "");
        setCaseId(changed.case_id || "");
        setStatus(changed.status);
        await onSaved();
      }}
    />
  ) : null;
  return (
    <>
      {detail}
      {(!current || editing) && (
        <Modal
          title={editing === "details" ? "编辑缺陷" : editing === "workflow" ? "更新处理状态" : "提交缺陷"}
          submitLabel={editing === "workflow" ? "确认更新" : editing === "create" ? "提交缺陷" : "保存修改"}
          onClose={() => (value ? setEditing(null) : onClose())}
          onSubmit={
            can(context, value ? "manage_defect" : "report")
              ? async (form) => {
                  const saved = await qualityApi.write<Defect>(
                    `${base}defects/${persistedId.current ? `${persistedId.current}/` : ""}`,
                    {
                      ...(value ? { expected_version: current?.edit_version || value.edit_version } : {}),
                      ...(editing !== "workflow"
                        ? {
                            title: form.get("title"),
                            description: form.get("description"),
                            severity: form.get("severity"),
                            affected_build: form.get("affected_build"),
                            ...(editing === "details"
                              ? {
                                  fixed_build: form.get("fixed_build") || "",
                                  ...(!value?.assignee_id && form.get("assignee_id")
                                    ? { assignee_id: form.get("assignee_id") }
                                    : {}),
                                }
                              : {}),
                          }
                        : {}),
                      ...(editing !== "details"
                        ? {
                            status,
                            ...(status === "closed"
                              ? {
                                  verification_method: verificationMethod,
                                  verification_note: form.get("verification_note") || "",
                                }
                              : {}),
                            fixed_build: form.get("fixed_build") || "",
                            resolution: form.get("resolution") || "",
                            ...(assigneeId !== (value?.assignee_id ?? "") ? { assignee_id: assigneeId || null } : {}),
                            repair_issue_id: form.get("repair_issue_id") || null,
                          }
                        : {}),
                      case_id: value?.source_execution ? value.case_id : caseId || null,
                      ...(form.get("regression_execution_id")
                        ? { regression_execution_id: form.get("regression_execution_id") }
                        : {}),
                    },
                    persistedId.current ? "patch" : "post"
                  );
                  persistedId.current = saved.id;
                  setCurrent(saved);
                  setStatus(saved.status);
                  try {
                    await uploadDefectFiles(base, saved.id, files);
                    setFiles([]);
                  } catch (e) {
                    const failure = new Error(
                      `缺陷已保存，附件未全部完成，请重试或进入详情补传：${e instanceof Error ? e.message : "上传失败"}`
                    );
                    Object.assign(failure, { cause: e });
                    throw failure;
                  }
                  await onSaved();
                }
              : undefined
          }
        >
          {!value && onFromSource && (
            <details className="text-12 text-secondary">
              <summary className="cursor-pointer">关联采集记录（可选）</summary>
              <button type="button" className="mt-2 text-accent-primary hover:underline" onClick={onFromSource}>
                按来源编号登记缺陷
              </button>
            </details>
          )}
          {editing === "workflow" && (
            <>
              <div className="space-y-1">
                <p className="text-12 font-medium text-accent-primary">{value?.code}</p>
                <p className="text-13 font-medium break-words">{value?.title}</p>
              </div>
              <Field label="处理状态">
                <select
                  aria-label="处理状态"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className={fieldClass}
                >
                  {Object.entries(statusNames).map(([key, name]) => {
                    const allowed = (transitions[value?.status || "open"] || ["open"]).includes(key);
                    const managerOnly = key === "closed" && !context.is_manager && value?.status !== "closed";
                    return (
                      <option key={key} value={key} disabled={!allowed || managerOnly}>
                        {name}
                        {key === value?.status
                          ? "（当前）"
                          : !allowed
                            ? key === "closed"
                              ? "（先修复并验证）"
                              : "（当前不可选）"
                            : managerOnly
                              ? "（由项目经理确认）"
                              : ""}
                      </option>
                    );
                  })}
                </select>
              </Field>
            </>
          )}
          {!value && (
            <Field label="图片和附件（可多选，单文件20MB以内）">
              <input
                type="file"
                multiple
                className={fieldClass}
                onChange={(event) => setFiles(Array.from(event.target.files || []))}
              />
              <span className="text-12 text-secondary"></span>
            </Field>
          )}
          {editing !== "workflow" && (
            <>
              <Field label="缺陷标题 *">
                <input required name="title" defaultValue={value?.title} maxLength={255} className={fieldClass} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="严重程度">
                  <select name="severity" defaultValue={value?.severity ?? "major"} className={fieldClass}>
                    {Object.entries(severityNames).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <Field label="重现步骤 / 实际表现">
                <textarea name="description" defaultValue={value?.description} rows={4} className={fieldClass} />
              </Field>
            </>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {editing !== "workflow" && (
              <Field label="影响版本">
                <input
                  name="affected_build"
                  defaultValue={value?.affected_build ?? defaultBuild}
                  className={fieldClass}
                />
              </Field>
            )}
            {(editing === "workflow" || editing === "details") && (
              <Field label="修复版本">
                <input
                  name="fixed_build"
                  required={status === "resolved"}
                  defaultValue={value?.fixed_build}
                  className={fieldClass}
                  placeholder="标记已修复时必填"
                />
              </Field>
            )}
          </div>
          {editing === "details" && value && context.is_manager && (
            <section className="space-y-3 border-t border-subtle pt-4">
              <h3 className="text-13 font-medium">处理安排</h3>
              <Field label="技术负责人">
                {value.assignee_id ? (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      {value.assignee_name || context.members.find((row) => row.id === value.assignee_id)?.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditingAssignee(true)}
                      className="text-12 text-accent-primary"
                    >
                      转派并交接
                    </button>
                  </div>
                ) : (
                  <select name="assignee_id" className={fieldClass}>
                    <option value="">暂不指派</option>
                    {context.members
                      .filter(
                        (row) =>
                          !context.business_roles_enabled ||
                          (row.business_roles || [row.business_role]).some(
                            (role) => typeof role === "string" && ["PLATFORM_ADMIN", "TECHNICIAN"].includes(role)
                          )
                      )
                      .map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                  </select>
                )}
              </Field>
              <Field label="处理分类">
                <DefectDispositionPanel
                  base={base}
                  value={value}
                  context={context}
                  onChanged={async (row) => {
                    setCurrent(row);
                    if (row.status === "closed") setEditing(null);
                    await onSaved();
                  }}
                />
              </Field>
            </section>
          )}
          <Field label="关联测试用例">
            <select
              name="case_id"
              disabled={!!value?.source_execution}
              value={caseId}
              onChange={(event) => setCaseId(event.target.value)}
              className={fieldClass}
            >
              <option value="">暂不关联</option>
              {cases?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </Field>
          {editing === "workflow" && (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="指派给">
                  <select
                    name="assignee_id"
                    value={assigneeId}
                    disabled={!!value?.assignee_id || (context.business_roles_enabled && !context.is_manager)}
                    onChange={(e) => setAssigneeId(e.target.value)}
                    className={fieldClass}
                  >
                    <option value="">未指派</option>
                    {context.members
                      .filter(
                        (m) =>
                          !context.business_roles_enabled ||
                          (m.business_roles || [m.business_role]).some(
                            (role) => typeof role === "string" && ["PLATFORM_ADMIN", "TECHNICIAN"].includes(role)
                          ) ||
                          m.id === assigneeId
                      )
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                  </select>
                </Field>
                {context.is_manager && context.business_roles_enabled && projectMembersPath(base) && (
                  <Link className="text-12 text-accent-primary hover:underline" to={projectMembersPath(base)!}>
                    成员与权限 · 设置技术员
                  </Link>
                )}
                <Field label="关联修复任务">
                  <PagedRecordSelect<{ id: string; name: string; code?: string }>
                    url={`${base}work-item-options/`}
                    name="repair_issue_id"
                    placeholder="暂不关联"
                    searchLabel="搜索修复任务"
                    required={false}
                    defaultValue={value?.repair_issue_id || ""}
                    defaultLabel={value?.repair_issue_name || "已关联修复任务"}
                    getLabel={(row) => row.name}
                  />
                </Field>
              </div>
              {value?.repair_issue_id && (
                <Link
                  className="text-13 text-accent-primary underline"
                  to={`${projectUrl}/issues/${value.repair_issue_id}`}
                >
                  打开关联修复任务
                </Link>
              )}
              <Field label="处理说明">
                <textarea name="resolution" defaultValue={value?.resolution} rows={2} className={fieldClass} />
              </Field>
            </>
          )}
          {value?.source_execution && (
            <div className="space-y-2 rounded-md border border-subtle p-3 text-12">
              <h3 className="font-medium">来源执行 · {value.source_execution.case_title}</h3>
              <p>
                {value.source_execution.plan_name} · {value.source_execution.build} ·{" "}
                {value.source_execution.environment}
              </p>
              <Badge value={value.source_execution.result} />
              <p className="whitespace-pre-wrap">{value.source_execution.actual_result}</p>
            </div>
          )}
          {status === "closed" &&
            value?.status === "resolved" &&
            context.is_manager &&
            value.manual_verification_allowed && (
              <Field label="验证方式 *">
                <select
                  className={fieldClass}
                  value={verificationMethod}
                  onChange={(event) => setVerificationMethod(event.target.value)}
                >
                  <option value="regression">关联测试用例回归</option>
                  <option value="manual">经理人工验证（简单手工缺陷）</option>
                </select>
              </Field>
            )}
          {status === "closed" && verificationMethod === "manual" && (
            <Field label="验证过程与结果 *">
              <textarea
                name="verification_note"
                required
                rows={3}
                maxLength={4000}
                className={fieldClass}
                placeholder="说明在哪个版本、按什么步骤验证，实际结果是什么。"
              />
            </Field>
          )}
          {status === "closed" && value?.status === "resolved" && verificationMethod !== "manual" && (
            <Field label="选择通过的回归执行 *">
              <select required name="regression_execution_id" className={fieldClass}>
                <option value="">选择本次修复后、修复版本的通过记录</option>
                {candidates?.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.plan_name} · {e.build} · {renderNumericDateTime(e.created_at)}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {editing === "workflow" && value?.status !== "resolved" && value?.status !== "closed" && (
            <p className="text-12 text-secondary">关闭缺陷：先更新为“已修复，待回归”，验证后再选“已关闭”。</p>
          )}
          {editingAssignee && value && (
            <DefectQuickEdit
              base={base}
              context={context}
              value={value}
              field="assignee"
              projectUrl={projectUrl}
              onClose={() => setEditingAssignee(false)}
              onSaved={async () => {
                const row = await qualityApi.read<Defect>(`${base}defects/${value.id}/`);
                setCurrent(row);
                await onSaved();
              }}
            />
          )}
        </Modal>
      )}
    </>
  );
}
