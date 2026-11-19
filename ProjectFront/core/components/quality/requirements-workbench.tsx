import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { lazy, Suspense, useState } from "react";
import useSWR from "swr";
import { Navigate, useParams, useSearchParams } from "react-router";
import { RequirementState, requirementStatuses } from "./requirement-state";
import { Badge } from "./record-badge";

import { ClipboardList, Plus, ChevronDown } from "lucide-react";
import { Button } from "@plane/ui";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";
import { PageHead } from "@/components/core/page-title";
import { qualityApi, errorMessage } from "./api";

import { TableHeaderFilter } from "./table-header-filter";
import { ListFilters } from "./list-filters";
import { pageSize, normalizedPageParams } from "./pagination";
import { RecordProgress } from "./record-progress";

import { Empty, Field, fieldClass, Modal, Paging } from "./shared";
import { can, priorityNames } from "./types";
import type { Context, Page } from "./types";
import { useWorkItemKinds } from "./work-item-kind";
import { SavedViewControls } from "./saved-view-controls";
import { LayoutControls, recordLayout } from "./layout-controls";
import { RecordPresentation } from "./record-presentation";

export type Requirement = {
  created_by_name?: string;
  created_at?: string;
  trashed_at?: string | null;
  id: string;
  title: string;
  description: string;
  acceptance: string;
  target_build: string;
  priority: string;
  sequence_id: number;
  number: number;
  code: string;
  status: string;
  development_state: string;
  development_group: string;
  version: number;
  case_count: number;
  revisions?: { id: string; version: number; snapshot: Record<string, string>; actor: string; created_at: string }[];
  cases?: { id: string; title: string; version: number }[];
  tasks?: { id: string; title: string; sequence_id: number; state: string; state_group: string }[];
};
const actions: Record<string, string> = {
  create: "创建需求",
  edit: "修改需求",
  submit: "提交审核",
  approve: "确认需求",
  return: "退回修改",
  accept: "验收完成",
  cancel: "取消需求",
  reopen: "重开需求",
  archive: "归档需求",
  restore: "恢复需求",
  trash: "删除需求",
  untrash: "从回收站恢复",
};
const requirementPriorityNames = { urgent: "紧急", ...priorityNames, none: "未设置" };
const statuses = requirementStatuses;
const panelLoading = (
  <div role="status" className="p-5 text-13 text-secondary">
    正在加载…
  </div>
);
const LinkedTaskPeek = lazy(() => import("./linked-task-peek").then((module) => ({ default: module.LinkedTaskPeek })));
const CaseForm = lazy(() => import("./case-form").then((module) => ({ default: module.CaseForm })));
const DocumentImportForm = lazy(() =>
  import("./document-import-form").then((module) => ({ default: module.DocumentImportForm }))
);

export function RequirementsWorkbench({
  embedded,
}: {
  embedded?: {
    id?: string;
    mode: "details" | "edit" | "create";
    defaultBuild?: string;
    onClose: () => void;
    onSaved: () => Promise<unknown>;
  };
} = {}) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const canonicalParams = useParams();
  const { data: workKinds, mutate: refreshKinds } = useWorkItemKinds(projectId);
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/`;
  const projectUrl = `/${workspaceSlug}/projects/${projectId}`;
  const { data: context } = useSWR(`${base}context/`, (url: string) => qualityApi.read<Context>(url));
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [editing, setEditing] = useState<Requirement | null | undefined>(
    embedded?.mode === "create" ? null : undefined
  );
  const [stateValue, setStateValue] = useState<Requirement>();
  const [activeTask, setActiveTask] = useState<string>();
  const openTask = (id: string) => {
    if (!workspaceSlug || !projectId) return;
    setActiveTask(id);
  };
  const [creatingCase, setCreatingCase] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selected, setSelected] = useState<Requirement>(),
    [action, setAction] = useState<string>(),
    [error, setError] = useState("");
  const {
    data,
    error: listError,
    mutate,
  } = useSWR(`${base}requirements/?${normalizedPageParams(params)}`, (url: string) =>
    qualityApi.read<Page<Requirement>>(url)
  );
  const {
    data: detail,
    error: detailError,
    mutate: refresh,
  } = useSWR(
    selected ? `${base}requirements/${selected.id}/?deleted=${params.get("deleted") === "true"}` : null,
    (url: string) => qualityApi.read<Requirement>(url)
  );
  const {
    data: linkedRequirement,
    mutate: refreshLinked,
    error: linkedError,
  } = useSWR(
    (embedded?.id || params.get("requirement")) && !selected
      ? `${base}requirements/${embedded?.id || params.get("requirement")}/`
      : null,
    (url: string) => qualityApi.read<Requirement>(url)
  );
  const {
    data: stateDetail,
    error: stateError,
    mutate: refreshStateDetail,
  } = useSWR(stateValue ? `${base}requirements/${stateValue.id}/` : null, (url: string) =>
    qualityApi.read<Requirement>(url)
  );
  const current = detail || selected || linkedRequirement;
  const editor = editing !== undefined ? editing : embedded?.mode === "edit" ? current : undefined;
  const saved = async () => {
    await refreshKinds();
    await mutate();
    await refresh();
    await refreshLinked();
    await refreshStateDetail();
    await embedded?.onSaved();
  };
  const workflow = async (verb: string, comment = "") => {
    if (!current) return;
    setError("");
    try {
      await qualityApi.write(`${base}requirements/${current.id}/workflow/`, {
        action: verb,
        expected_version: current.version,
        comment,
      });
      if (verb === "trash" || verb === "untrash") {
        setSelected(undefined);
        if (embedded) embedded.onClose();
        else {
          const next = new URLSearchParams(params);
          next.delete("requirement");
          if (verb === "untrash") next.delete("deleted");
          setParams(next);
        }
        await mutate();
        await refreshKinds();
        await embedded?.onSaved();
      } else await saved();
    } catch (e) {
      setError(errorMessage(e));
      throw e;
    }
  };
  const rowActions = (row: Requirement) =>
    context && (
      <>
        <Button type="button" size="sm" variant="neutral-primary" onClick={() => setSelected(row)}>
          查看 / 处理
        </Button>
        {!row.trashed_at && can(context, "knowledge_write") && ["draft", "approved"].includes(row.status) && (
          <Button type="button" size="sm" variant="neutral-primary" onClick={() => setEditing(row)}>
            编辑
          </Button>
        )}
        {context.is_manager &&
          (row.trashed_at ? (
            <Button
              type="button"
              size="sm"
              variant="neutral-primary"
              onClick={() => {
                setSelected(row);
                setAction("untrash");
              }}
            >
              恢复
            </Button>
          ) : (
            ["draft", "cancelled"].includes(row.status) && (
              <Button
                type="button"
                size="sm"
                variant="neutral-primary"
                onClick={() => {
                  setSelected(row);
                  setAction("trash");
                }}
              >
                删除
              </Button>
            )
          ))}
      </>
    );
  if (
    !embedded &&
    canonicalParams.projectId &&
    context?.identifier &&
    canonicalParams.projectId.toLowerCase() !== context.identifier.toLowerCase()
  )
    return (
      <Navigate replace to={`/${workspaceSlug}/p/${encodeURIComponent(context.identifier)}/requirements/?${params}`} />
    );
  return (
    <div className={embedded ? "contents" : "platform-workspace flex h-full min-h-0 flex-col bg-surface-1"}>
      <PageHead title={`${context?.project_name || "项目"} · 需求`} />
      {!embedded && (
        <>
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle px-5 py-4">
            <div className="flex items-center gap-2">
              <AppSidebarToggleButton onlyWhenCollapsed />
              <ClipboardList className="size-4" />
              <h1 className="platform-page-title">需求</h1>
              <span className="text-12 text-secondary">
                {context?.project_name}
                {workKinds ? ` · ${workKinds.requirements} 条需求` : ""}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {context && (
                <ListFilters compact kind="requirements" context={context} params={params} onApply={setParams} />
              )}
              <SavedViewControls kind="requirements" params={params} onApply={setParams} />
              <LayoutControls params={params} onApply={setParams} />
              <Link className="text-13 text-secondary hover:text-primary" to={`${projectUrl}/issues/`}>
                查看任务
              </Link>
              <Link className="text-13 text-secondary" to={`${projectUrl}/quality?tab=cases`}>
                查看关联用例
              </Link>
              {context?.is_manager && (
                <Button variant="neutral-primary" onClick={() => setImporting(true)}>
                  导入文档
                </Button>
              )}
              {context && can(context, "knowledge_write") && (
                <Button onClick={() => setEditing(null)}>
                  <Plus className="mr-1 size-4" />
                  新建需求
                </Button>
              )}
            </div>
          </header>
          <main className="min-h-0 flex-1 space-y-5 overflow-auto p-5">
            {listError && (
              <p role="alert" className="text-13 text-danger-primary">
                {errorMessage(listError)}
              </p>
            )}
            {!data && !listError && (
              <p role="status" className="text-13 text-secondary">
                正在加载需求…
              </p>
            )}
            {data?.count === 0 && recordLayout(params) !== "table" && (
              <Empty>暂无需求。记录要做的事和验收标准；需要回归验证时，再关联测试用例。</Empty>
            )}
            {data && data.count > 0 && recordLayout(params) !== "table" && (
              <RecordPresentation
                onStatusChange={(id) => setStateValue(data.results.find((row) => row.id === id))}
                canChangeStatus={(id) =>
                  !!context && can(context, "knowledge_write") && !data.results.find((row) => row.id === id)?.trashed_at
                }
                kind="requirements"
                context={context}
                layout={recordLayout(params)}
                columns={["优先级", "目标版本", "测试覆盖"]}
                rows={data.results.map((row) => ({
                  id: row.id,
                  title: `${row.code} · ${row.title}`,
                  subtitle: `需求版本 v${row.version} · 创建人：${row.created_by_name || "未记录"}`,
                  status: row.status,
                  statusName: statuses[row.status],
                  values: [
                    requirementPriorityNames[row.priority as keyof typeof requirementPriorityNames] || row.priority,
                    row.target_build || "待安排",
                    row.case_count ? `${row.case_count} 条用例` : "用例可选",
                  ],
                }))}
                renderActions={(id) => {
                  const row = data.results.find((item) => item.id === id);
                  return row ? rowActions(row) : null;
                }}
                onOpen={(id) => {
                  setSelected(data.results.find((row) => row.id === id));
                  setError("");
                }}
              />
            )}
            {data && recordLayout(params) === "table" && (
              <div className="overflow-auto rounded-md border border-subtle">
                <table className="w-full text-left text-13">
                  <thead className="border-b border-subtle bg-layer-1 text-secondary">
                    <tr>
                      <th className="p-3">
                        <TableHeaderFilter label="需求" kind="requirements" context={context} />
                      </th>
                      <th className="p-3">
                        <TableHeaderFilter label="状态" kind="requirements" context={context} />
                      </th>
                      <th className="p-3">
                        <TableHeaderFilter label="优先级" kind="requirements" context={context} />
                      </th>
                      <th className="p-3">
                        <TableHeaderFilter label="目标版本" kind="requirements" context={context} />
                      </th>
                      <th className="p-3">测试覆盖</th>
                      <th className="p-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!data.results.length && (
                      <tr>
                        <td colSpan={6} className="p-6 text-center text-13 text-secondary" role="status">
                          没有匹配记录，可调整表头筛选条件。
                        </td>
                      </tr>
                    )}
                    {data.results.map((row) => (
                      <tr key={row.id} className="border-b border-subtle hover:bg-layer-1">
                        <td className="p-3">
                          <button
                            className="platform-record-link text-left text-13"
                            onClick={() => {
                              setSelected(row);
                              setError("");
                            }}
                          >
                            {row.code} · {row.title}
                          </button>
                          <p className="mt-1 text-11 text-secondary">
                            需求版本 v{row.version} · 创建人：{row.created_by_name || "未记录"}
                          </p>
                        </td>
                        <td className="p-3">
                          {context && can(context, "knowledge_write") && !row.trashed_at ? (
                            <button
                              type="button"
                              aria-label={`更新需求状态：${row.title}`}
                              onClick={() => setStateValue(row)}
                            >
                              <Badge value={row.status} label={statuses[row.status]} />
                            </button>
                          ) : (
                            <Badge value={row.status} label={statuses[row.status]} />
                          )}
                        </td>
                        <td className="p-3">
                          {requirementPriorityNames[row.priority as keyof typeof requirementPriorityNames] ||
                            row.priority}
                        </td>
                        <td className="p-3">{row.target_build || "待安排"}</td>
                        <td className="p-3">{row.case_count ? `${row.case_count} 条用例` : "未关联用例（可选）"}</td>
                        <td className="p-3">
                          <div className="flex flex-wrap gap-2">{rowActions(row)}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {data && (
              <Paging
                perPage={pageSize(params)}
                onPageSizeChange={(size) => {
                  const next = new URLSearchParams(params);
                  next.set("per_page", String(size));
                  next.delete("page");
                  setParams(next);
                }}
                page={page}
                count={data.count}
                onChange={(value) => {
                  const next = new URLSearchParams(params);
                  next.set("page", String(value));
                  setParams(next);
                }}
              />
            )}
          </main>
        </>
      )}
      {stateValue && (!stateDetail || stateDetail.version < stateValue.version) && (
        <Modal title="更新需求状态" onClose={() => setStateValue(undefined)}>
          <p className="text-13 text-secondary">{stateError ? errorMessage(stateError) : "正在加载…"}</p>
        </Modal>
      )}
      {stateValue && stateDetail && stateDetail.version >= stateValue.version && context && (
        <RequirementState
          key={`${stateDetail.id}-${stateDetail.version}`}
          base={base}
          value={stateDetail}
          context={context}
          onClose={() => setStateValue(undefined)}
          onSaved={saved}
        />
      )}
      {activeTask && (
        <Suspense fallback={panelLoading}>
          <LinkedTaskPeek
            id={activeTask}
            onClosed={() => {
              setActiveTask(undefined);
              void saved();
            }}
          />
        </Suspense>
      )}
      {embedded?.id && !current && (
        <Modal title="需求详情" onClose={embedded.onClose}>
          <p className="text-13 text-secondary">{linkedError ? errorMessage(linkedError) : "正在加载需求…"}</p>
        </Modal>
      )}
      {importing && (
        <Suspense fallback={panelLoading}>
          <DocumentImportForm base={base} resource="requirements" onClose={() => setImporting(false)} onSaved={saved} />
        </Suspense>
      )}
      {editor !== undefined && context && (
        <Modal
          title={editor ? "编辑需求" : "新建需求"}
          onClose={() =>
            embedded?.mode === "edit" || embedded?.mode === "create" ? embedded.onClose() : setEditing(undefined)
          }
          onSubmit={async (form) => {
            await qualityApi.write(
              `${base}requirements/${editor ? `${editor.id}/` : ""}`,
              {
                title: form.get("title"),
                description: form.get("description"),
                acceptance: form.get("acceptance"),
                target_build: form.get("target_build"),
                priority: form.get("priority"),
                ...(editor ? { expected_version: editor.version } : {}),
              },
              editor ? "patch" : "post"
            );
            await saved();
          }}
        >
          <Field label="需求标题 *">
            <input name="title" required maxLength={255} defaultValue={editor?.title} className={fieldClass} />
          </Field>
          <Field label="需求说明">
            <textarea
              name="description"
              rows={4}
              maxLength={20000}
              defaultValue={editor?.description}
              className={fieldClass}
              placeholder="用户需要解决什么问题？期望发生什么？"
            />
          </Field>
          <Field label="验收标准">
            <textarea
              name="acceptance"
              rows={4}
              maxLength={20000}
              defaultValue={editor?.acceptance}
              className={fieldClass}
              placeholder="写出可验证的完成条件，例如：某页面增加指定提示，并核对显示；复杂需求可列出验证场景"
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="优先级">
              <select name="priority" defaultValue={editor?.priority || "medium"} className={fieldClass}>
                {Object.entries(requirementPriorityNames).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="目标版本">
              <input
                name="target_build"
                maxLength={120}
                defaultValue={editor?.target_build ?? embedded?.defaultBuild}
                className={fieldClass}
              />
            </Field>
          </div>
        </Modal>
      )}
      {current && context && editor === undefined && !creatingCase && !action && !activeTask && !stateValue && (
        <Modal
          title="需求详情"
          width="wide"
          onClose={() => {
            if (embedded) {
              embedded.onClose();
              return;
            }
            setSelected(undefined);
            const next = new URLSearchParams(params);
            next.delete("requirement");
            setParams(next);
          }}
        >
          <RecordProgress base={base} kind="requirement" id={current.id} projectUrl={projectUrl} />
          <p className="text-12 text-secondary">
            创建人：{current.created_by_name || "未记录"}
            {current.created_at ? " · " + renderNumericDateTime(current.created_at) : ""}
          </p>
          <div className="record-detail-heading flex flex-wrap items-start justify-between gap-3">
            <h3 className="text-20 font-semibold">{current.title}</h3>
            <div className="flex items-center gap-2 text-12 text-secondary">
              {can(context, "knowledge_write") && !current.trashed_at ? (
                <button
                  type="button"
                  aria-label="更新需求状态"
                  className="inline-flex items-center gap-1"
                  onClick={() => setStateValue(current)}
                >
                  <Badge value={current.status} label={statuses[current.status]} />
                  <ChevronDown className="size-3" />
                </button>
              ) : (
                <Badge value={current.status} label={statuses[current.status]} />
              )}{" "}
              · v{current.version}
            </div>
          </div>
          {detailError && (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(detailError)}
            </p>
          )}
          <p className="text-12 text-secondary">
            {current.code} · {requirementPriorityNames[current.priority as keyof typeof requirementPriorityNames]} ·
            目标版本：
            {current.target_build || "待安排"}
          </p>
          <section className="space-y-2">
            <h4 className="text-13 font-medium">需求说明</h4>
            <p className="text-13 leading-7 whitespace-pre-wrap">{current.description || "暂未填写。"}</p>
          </section>
          <section className="space-y-2">
            <h4 className="text-13 font-medium">验收标准</h4>
            <p className="text-13 leading-7 whitespace-pre-wrap">
              {current.acceptance || "提交审核前请补充验收标准。"}
            </p>
          </section>
          <p className="text-12 text-secondary">开发状态：{current.development_state || "待安排"}</p>
          <div className="flex flex-wrap gap-2">
            {!current.trashed_at &&
              can(context, "knowledge_write") &&
              ["draft", "approved"].includes(current.status) && (
                <Button type="button" variant="neutral-primary" onClick={() => setEditing(current)}>
                  编辑需求
                </Button>
              )}
            {!current.trashed_at && can(context, "knowledge_write") && current.status === "draft" && (
              <Button
                type="button"
                onClick={() => {
                  void workflow("submit").catch(() => undefined);
                }}
              >
                提交审核
              </Button>
            )}
            {context.is_manager && current.status === "review" && (
              <>
                <Button
                  type="button"
                  onClick={() => {
                    void workflow("approve").catch(() => undefined);
                  }}
                >
                  确认需求
                </Button>
                <Button type="button" variant="neutral-primary" onClick={() => setAction("return")}>
                  退回修改
                </Button>
              </>
            )}
            {context.is_manager && (
              <>
                {current.trashed_at ? (
                  <Button type="button" variant="neutral-primary" onClick={() => setAction("untrash")}>
                    从回收站恢复
                  </Button>
                ) : (
                  ["draft", "cancelled"].includes(current.status) && (
                    <Button type="button" variant="neutral-primary" onClick={() => setAction("trash")}>
                      删除需求
                    </Button>
                  )
                )}

                {!current.trashed_at && current.status === "approved" && (
                  <Button type="button" onClick={() => setAction("accept")}>
                    记录验收
                  </Button>
                )}
                {!current.trashed_at && ["draft", "review", "approved"].includes(current.status) && (
                  <Button type="button" variant="neutral-primary" onClick={() => setAction("cancel")}>
                    取消需求
                  </Button>
                )}
                {!current.trashed_at && ["completed", "cancelled"].includes(current.status) && (
                  <>
                    <Button type="button" variant="neutral-primary" onClick={() => setAction("reopen")}>
                      重开需求
                    </Button>
                    <Button type="button" variant="neutral-primary" onClick={() => setAction("archive")}>
                      归档
                    </Button>
                  </>
                )}
                {!current.trashed_at && current.status === "archived" && (
                  <Button type="button" variant="neutral-primary" onClick={() => setAction("restore")}>
                    恢复需求
                  </Button>
                )}
              </>
            )}
            <Link className="self-center text-13 text-accent-primary" to={`${projectUrl}/issues/${current.id}`}>
              查看开发工作项 ↗
            </Link>
          </div>
          {error && (
            <p role="alert" className="text-13 text-danger-primary">
              {error}
            </p>
          )}
          <section className="space-y-3 border-t border-subtle pt-4">
            <h4 className="text-13 font-medium">开发任务 · {current.tasks?.length || 0}</h4>
            {current.tasks?.map((task) => (
              <div
                key={task.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-subtle px-3 py-2"
              >
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    openTask(task.id);
                  }}
                  className="min-w-0 flex-1 text-left text-13 text-accent-primary"
                >
                  {context.identifier}-T-{task.sequence_id} · {task.title}{" "}
                  <span className="text-secondary">{task.state}</span>
                </button>
                <Button
                  type="button"
                  size="sm"
                  variant="neutral-primary"
                  onClick={(event) => {
                    event.stopPropagation();
                    openTask(task.id);
                  }}
                >
                  查看 / 编辑
                </Button>
              </div>
            ))}
            {!current.trashed_at &&
              can(context, "knowledge_write") &&
              ["draft", "approved"].includes(current.status) && (
                <Button type="button" variant="neutral-primary" onClick={() => setAction("task")}>
                  拆分开发任务
                </Button>
              )}
          </section>
          <section className="space-y-3 border-t border-subtle pt-4">
            <h4 className="text-13 font-medium">关联测试用例 · {current.case_count}（可选）</h4>
            <p className="text-12 text-secondary"></p>
            {current.cases?.map((item) => (
              <p key={item.id} className="text-13">
                {item.title} · v{item.version}
              </p>
            ))}
            {can(context, "manage_case") && (
              <Button type="button" variant="neutral-primary" onClick={() => setCreatingCase(true)}>
                新建关联用例
              </Button>
            )}
            <Link className="ml-3 text-13 text-accent-primary" to={`${projectUrl}/quality?tab=cases`}>
              查看用例库 →
            </Link>
          </section>
          <details className="text-12">
            <summary className="cursor-pointer text-secondary">变更历史（{current.revisions?.length || 0}）</summary>
            {current.revisions?.map((revision) => (
              <div key={revision.id} className="mt-3 border-l-2 border-subtle pl-3">
                <p>
                  v{revision.version} · {actions[revision.snapshot.action] || "变更需求"} ·{" "}
                  {statuses[revision.snapshot.status]}
                </p>
                <p className="mt-1 text-secondary">
                  {revision.actor} · {renderNumericDateTime(revision.created_at)}
                </p>
                {revision.snapshot.comment && (
                  <p className="mt-1 whitespace-pre-wrap">审核意见：{revision.snapshot.comment}</p>
                )}
                <p className="mt-1 whitespace-pre-wrap text-secondary">需求：{revision.snapshot.title}</p>
                <p className="mt-1 whitespace-pre-wrap text-secondary">
                  说明：{revision.snapshot.description || "未填写"}
                </p>
                <p className="mt-1 whitespace-pre-wrap text-secondary">
                  验收标准：{revision.snapshot.acceptance || "未填写"}
                </p>
              </div>
            ))}
          </details>
        </Modal>
      )}
      {creatingCase && current && context && (
        <Suspense fallback={panelLoading}>
          <CaseForm
            base={base}
            context={context}
            requirementId={current.id}
            onClose={() => setCreatingCase(false)}
            onSaved={saved}
          />
        </Suspense>
      )}
      {action === "task" && current && (
        <Modal
          title="拆分开发任务"
          onClose={() => setAction(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}requirements/${current.id}/tasks/`, {
              title: form.get("title"),
              description: form.get("description"),
              assignee_id: form.get("assignee_id") || null,
            });
            await saved();
          }}
        >
          <Field label="开发任务标题 *">
            <input required name="title" maxLength={255} className={fieldClass} />
          </Field>
          <Field label="任务说明">
            <textarea name="description" rows={3} maxLength={20000} className={fieldClass} />
          </Field>
          <Field label="负责人">
            <select name="assignee_id" className={fieldClass}>
              <option value="">待分派</option>
              {context?.members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </select>
          </Field>
          <p className="text-12 text-secondary">新建关联任务</p>
        </Modal>
      )}
      {action && action !== "task" && (
        <Modal
          title={actions[action] || "需求状态调整"}
          onClose={() => setAction(undefined)}
          onSubmit={async (form) => {
            await workflow(action, String(form.get("comment")));
          }}
        >
          {action === "trash" && (
            <p className="text-12 text-secondary">
              移入回收站，可恢复；历史修订与测试证据保留。仍有关联开发任务时需先处理任务关系。
            </p>
          )}
          <Field label={action === "accept" ? "验收过程与结果 *" : "原因 *"}>
            <textarea name="comment" required maxLength={4000} rows={3} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </div>
  );
}
