import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { pageSize } from "./pagination";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Navigate, useParams, useSearchParams } from "react-router";
import { Button, CustomMenu } from "@plane/ui";
import { Plus, ChevronDown, ArrowLeft, RefreshCw, GitBranch, CalendarRange, Flag, List } from "lucide-react";
import { VersionEventHistory } from "./version-event-history";
import { VersionAcceptancePanel } from "./version-acceptance-panel";
import { PageHead } from "@/components/core/page-title";
import { LinkedTaskPeek } from "./linked-task-peek";
import { VersionRecords } from "./version-records";
import type { LinkedRecordKind, LinkedRecordMode } from "./version-records";
import { VersionRecordDialog } from "./version-record-dialog";
import type { VersionRecordTarget } from "./version-record-dialog";
import { qualityApi, errorMessage } from "./api";
import { can } from "./types";
import type { Context, Page } from "./types";
import { Modal, Field, fieldClass, Paging, Empty } from "./shared";
import { VersionForm, VersionNodeForm } from "./version-forms";
import { VersionPhases, VersionTimeline, VersionFlow, VersionMilestones } from "./version-visuals";
import { versionStatuses, flowStatuses, nodeKinds } from "./version-types";
import type { FlowNode, VersionDetail, VersionSummary } from "./version-types";
const displays = [
  { key: "list", title: "列表", icon: List },
  { key: "timeline", title: "时间轴", icon: CalendarRange },
  { key: "milestones", title: "里程碑", icon: Flag },
  { key: "flow", title: "流程图", icon: GitBranch },
];
export function VersionsWorkbench() {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const canonicalParams = useParams();
  const [params, setParams] = useSearchParams();
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/`;
  const projectUrl = `/${workspaceSlug}/projects/${projectId}`;
  const { data: context } = useSWR(`${base}context/`, (url: string) => qualityApi.read<Context>(url));
  const perPage = pageSize(params);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const view = params.get("display") || "list";
  const acceptance = params.get("tab") === "acceptance";
  const selected = acceptance ? null : params.get("version");
  const {
    data: rows,
    error: listError,
    mutate: refreshList,
  } = useSWR(acceptance ? null : `${base}versions/?page=${page}&per_page=${perPage}`, (url: string) =>
    qualityApi.read<Page<VersionSummary>>(url)
  );
  const {
    data: version,
    error: detailError,
    mutate: refreshVersion,
  } = useSWR(selected ? `${base}versions/${selected}/` : null, (url: string) => qualityApi.read<VersionDetail>(url));
  const [activeTask, setActiveTask] = useState<string>();
  const [recordTarget, setRecordTarget] = useState<VersionRecordTarget>();
  const [form, setForm] = useState<"new" | "edit">();
  const [editingFlow, setEditingFlow] = useState(false);
  const [nodeForm, setNodeForm] = useState<FlowNode | null | undefined>();
  const [nodeRemoval, setNodeRemoval] = useState<FlowNode>();
  const [nodeDetail, setNodeDetail] = useState<FlowNode>();
  const [action, setAction] = useState<string>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const writable = !!context && can(context, "manage_test");
  const finished = version?.status === "released" || version?.status === "cancelled";
  const set = (values: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values))
      if (value === null) next.delete(key);
      else next.set(key, value);
    setParams(next);
  };
  const saved = async (row: VersionDetail) => {
    set({ version: row.id });
    await refreshList();
    await refreshVersion(row);
  };
  const sync = async () => {
    if (!version) return;
    setBusy(true);
    setError("");
    try {
      const row = await qualityApi.write<VersionDetail>(`${base}versions/${version.id}/sync/`, {});
      await saved(row);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const recordsSaved = async () => {
    await refreshVersion();
    await refreshList();
  };
  const openRecord = (kind: LinkedRecordKind, id: string, mode: LinkedRecordMode = "details") => {
    if (kind === "issue") {
      if (!workspaceSlug || !projectId) return;
      setActiveTask(id);
    } else setRecordTarget({ kind, id, mode });
  };
  if (
    canonicalParams.projectId &&
    context?.identifier &&
    canonicalParams.projectId.toLowerCase() !== context.identifier.toLowerCase()
  )
    return (
      <Navigate replace to={`/${workspaceSlug}/p/${encodeURIComponent(context.identifier)}/versions/?${params}`} />
    );
  if (acceptance)
    return (
      <div className="flex h-full min-h-0 flex-col bg-surface-1">
        <PageHead title={`${context?.project_name || "项目"} · 发布验收`} />
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle p-4">
          <h1 className="text-18 font-semibold">版本迭代</h1>
          <Button variant="neutral-primary" onClick={() => set({ tab: null })}>
            返回版本列表
          </Button>
        </header>
        {context ? (
          <VersionAcceptancePanel base={base} context={context} />
        ) : (
          <p role="status" className="p-5 text-13 text-secondary">
            正在读取项目权限…
          </p>
        )}
      </div>
    );
  return (
    <main className="platform-workspace flex h-full min-w-0 flex-col overflow-y-auto bg-surface-1">
      <PageHead title={`${context?.project_name || "项目"} · 版本迭代`} />
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle p-4">
        <div>
          <p className="mb-1 text-11 text-secondary">{context?.project_name}</p>
          <h1 className="text-18 font-semibold">版本迭代</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="neutral-primary" onClick={() => set({ tab: "acceptance" })}>
            发布验收
          </Button>
          <CustomMenu
            placement="bottom-end"
            closeOnSelect
            customButton={
              <span className="flex items-center gap-2 rounded-md border border-subtle px-3 py-2 text-12 whitespace-nowrap text-secondary">
                显示方式
                <ChevronDown className="size-3" />
              </span>
            }
          >
            {displays.map((item) => (
              <CustomMenu.MenuItem key={item.key} onClick={() => set({ display: item.key })}>
                <item.icon className="size-4" />
                {item.title}
                {view === item.key ? " ✓" : ""}
              </CustomMenu.MenuItem>
            ))}
          </CustomMenu>
          {writable && (
            <Button variant="neutral-primary" onClick={() => setForm("new")}>
              <Plus className="mr-1 size-3.5" />
              新建版本
            </Button>
          )}
        </div>
      </header>
      <div className="space-y-5 p-4 sm:p-6">
        {(error || listError || detailError) && (
          <p role="alert" className="text-13 text-danger-primary">
            {error || errorMessage(listError || detailError)}
          </p>
        )}
        {!version && (
          <>
            {view === "timeline" && rows ? (
              <VersionTimeline rows={rows.results} onSelect={(id) => set({ version: id })} />
            ) : (
              <div className="space-y-2">
                {rows?.results.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    onClick={() => set({ version: row.id })}
                    className="flex w-full flex-wrap items-center justify-between gap-3 rounded-md border border-subtle p-4 text-left hover:bg-layer-1"
                  >
                    <span>
                      <strong className="platform-record-link text-14">{row.version}</strong>
                      {row.code && <span className="ml-2 text-11 text-secondary">{row.code}</span>}
                      <span className="platform-record-link ml-3 text-13">{row.name}</span>
                      <span className="mt-1 block text-11 text-secondary">
                        创建人：{row.created_by_name || "未记录"}
                      </span>
                      <span className="mt-2 block text-11 text-secondary">
                        {row.owner_name || "未指定负责人"} · {row.start_date?.replaceAll("-", "/") || "待安排"} —{" "}
                        {row.target_date?.replaceAll("-", "/") || "待安排"}
                      </span>
                    </span>
                    <span className="rounded-full bg-layer-1 px-3 py-1 text-12 text-secondary">
                      {versionStatuses[row.status]}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {rows?.count === 0 && <Empty>还没有版本计划。</Empty>}
            {rows && (
              <Paging
                page={page}
                count={rows.count}
                perPage={perPage}
                onPageSizeChange={(size) => set({ per_page: String(size), page: "1" })}
                onChange={(value) => set({ page: String(value) })}
              />
            )}
          </>
        )}
        {version && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <button
                  type="button"
                  onClick={() => set({ version: null })}
                  className="mb-2 flex items-center gap-1 text-12 text-secondary"
                >
                  <ArrowLeft className="size-3" />
                  版本列表
                </button>
                <h2 className="text-18 font-semibold">
                  {version.version} · {version.name}
                </h2>
                <p className="mt-2 text-12 text-secondary">
                  创建人：{version.created_by_name || "未记录"} · 负责人：
                  {version.owner_name} ·{" "}
                  {version.target_date ? `目标 ${version.target_date.replaceAll("-", "/")}` : "目标日期待安排"}
                  {version.cycle_name ? ` · ${version.cycle_name}` : ""}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {writable && !finished && (
                  <>
                    <Button
                      variant="neutral-primary"
                      disabled={version.automation_enabled}
                      onClick={() => setForm("edit")}
                    >
                      编辑计划
                    </Button>

                    <Button
                      variant="neutral-primary"
                      disabled={version.automation_enabled}
                      onClick={() => setEditingFlow(true)}
                    >
                      编辑流程与分工
                    </Button>
                    <Button
                      variant="neutral-primary"
                      onClick={() => setAction(version.automation_enabled ? "disable_automation" : "enable_automation")}
                    >
                      {version.automation_enabled ? "自动流转" : "跟踪模式"}
                      <ChevronDown className="ml-1 size-3" />
                    </Button>
                    <CustomMenu
                      placement="bottom-end"
                      closeOnSelect
                      customButton={
                        <span className="inline-flex shrink-0 items-center rounded-md border border-subtle px-3 py-2 text-12 whitespace-nowrap text-secondary">
                          阶段操作 ▾
                        </span>
                      }
                    >
                      <CustomMenu.MenuItem onClick={() => setAction("advance")}>
                        {version.status === "ready" ? "确认版本发布" : "进入下一阶段"}
                      </CustomMenu.MenuItem>
                      <CustomMenu.MenuItem onClick={() => setAction("back")}>退回上一阶段</CustomMenu.MenuItem>
                      <CustomMenu.MenuItem onClick={() => setAction("cancel")}>取消此版本</CustomMenu.MenuItem>
                    </CustomMenu>
                  </>
                )}
                <Button
                  variant="neutral-primary"
                  disabled={busy}
                  onClick={() => (writable ? void sync() : void refreshVersion())}
                >
                  <RefreshCw className="size-3.5" />
                </Button>
              </div>
            </div>
            <VersionPhases status={version.status} />
            {version.description && (
              <p className="text-13 leading-6 whitespace-pre-wrap text-secondary">{version.description}</p>
            )}
            {view === "timeline" ? (
              <VersionTimeline
                rows={[version]}
                onSelect={writable && !finished && !version.automation_enabled ? () => setForm("edit") : undefined}
              />
            ) : view === "milestones" ? (
              <VersionMilestones version={version} onSelect={setNodeDetail} />
            ) : view === "flow" ? (
              <VersionFlow
                version={version}
                onSelect={setNodeDetail}
                onEdit={writable && !finished && !version.automation_enabled ? setNodeForm : undefined}
              />
            ) : (
              context && (
                <VersionRecords
                  version={version}
                  context={context}
                  writable={writable}
                  finished={finished}
                  onOpen={openRecord}
                  onCreate={(kind) => setRecordTarget({ kind, mode: "create" })}
                  onLinkTask={() => setNodeForm(null)}
                />
              )
            )}
            {version.automation_note && version.automation_note.includes("暂停") && (
              <p role="status" className="text-12 text-warning-primary">
                {version.automation_note}
              </p>
            )}
            {version.flow_nodes.length > 0 && (
              <details className="text-12 text-secondary">
                <summary className="cursor-pointer">节点明细 · {version.flow_nodes.length}</summary>
                <div className="mt-3 space-y-2">
                  {version.flow_nodes.map((node) => (
                    <div
                      key={node.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded border border-subtle p-3"
                    >
                      <button type="button" onClick={() => setNodeDetail(node)} className="text-left text-13">
                        {node.name}{" "}
                        <span className="ml-2 text-11 text-secondary">
                          {nodeKinds[node.kind]} · {flowStatuses[version.flow_state[node.id]?.status]}
                        </span>
                      </button>
                      {writable && !finished && !version.automation_enabled && (
                        <button type="button" className="text-12 text-accent-primary" onClick={() => setNodeForm(node)}>
                          编辑
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}
            <details className="space-y-3 text-12 text-secondary">
              <summary className="cursor-pointer">
                发布前检查 · {version.blockers.length ? `${version.blockers.length} 项待处理` : "当前条件满足"}
              </summary>
              <div className="mt-3 space-y-2">
                {version.blockers.map((text) => (
                  <p key={text} className="text-warning-primary">
                    {text}
                  </p>
                ))}
                {version.quality_release_id && (
                  <Link to={`${projectUrl}/quality?tab=releases`}>查看关联发布检查 →</Link>
                )}
                <p>版本发布记录业务交付，不会自动部署外部系统。</p>
              </div>
            </details>
            <VersionEventHistory base={base} version={version} />
          </>
        )}
      </div>
      {activeTask && (
        <LinkedTaskPeek
          id={activeTask}
          onClosed={() => {
            setActiveTask(undefined);
            void recordsSaved();
          }}
        />
      )}
      {recordTarget && context && version && (
        <VersionRecordDialog
          target={recordTarget}
          base={base}
          projectUrl={projectUrl}
          context={context}
          build={version.version}
          onClose={() => setRecordTarget(undefined)}
          onSaved={recordsSaved}
        />
      )}
      {form && context && (
        <VersionForm
          base={base}
          value={form === "edit" ? version : undefined}
          context={context}
          onClose={() => setForm(undefined)}
          onSaved={(row) => {
            setForm(undefined);
            void saved(row);
          }}
        />
      )}
      {editingFlow && version && context && (
        <Modal title="编辑流程与分工" width="wide" onClose={() => setEditingFlow(false)}>
          <div className="flex items-center justify-between gap-3">
            <Button size="sm" variant="neutral-primary" onClick={() => setNodeForm(null)}>
              添加节点
            </Button>
          </div>
          <div className="max-h-[55vh] space-y-2 overflow-y-auto">
            {version.flow_nodes.map((node) => (
              <div
                key={node.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-13 font-medium">{node.name}</p>
                  <p className="mt-1 text-11 text-secondary">
                    {nodeKinds[node.kind]} ·{" "}
                    {context.members.find((member) => member.id === node.owner_id)?.name || "手动分派"} ·{" "}
                    {node.depends_on.length
                      ? `${node.depends_on.length} 个前置 / ${node.join === "all" ? "全部完成" : "任一完成"}`
                      : "起始节点"}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="neutral-primary" onClick={() => setNodeForm(node)}>
                    编辑
                  </Button>
                  <Button size="sm" variant="neutral-primary" onClick={() => setNodeRemoval(node)}>
                    移除节点
                  </Button>
                </div>
              </div>
            ))}
            {!version.flow_nodes.length && (
              <p className="py-5 text-13 text-secondary">暂无节点，点击“添加节点”开始。</p>
            )}
          </div>
        </Modal>
      )}
      {nodeRemoval && version && (
        <Modal
          title="从流程移除节点"
          onClose={() => setNodeRemoval(undefined)}
          submitLabel="确认移除"
          onSubmit={
            version.flow_nodes.some((node) => node.depends_on.includes(nodeRemoval.id))
              ? undefined
              : async () => {
                  const row = await qualityApi.write<VersionDetail>(
                    `${base}versions/${version.id}/`,
                    {
                      expected_version: version.edit_version,
                      flow_nodes: version.flow_nodes.filter((node) => node.id !== nodeRemoval.id),
                    },
                    "patch"
                  );
                  await saved(row);
                }
          }
        >
          <p className="text-13 font-medium">{nodeRemoval.name}</p>
          <p className="text-12 text-secondary">只移除流程节点，关联的业务记录仍保留。调整流程后，里程碑需重新确认。</p>
          {version.flow_nodes.some((node) => node.depends_on.includes(nodeRemoval.id)) && (
            <p className="text-12 text-warning-primary">其他节点仍依赖此节点，请先调整它们的前置条件。</p>
          )}
        </Modal>
      )}
      {nodeForm !== undefined && version && context && (
        <VersionNodeForm
          base={base}
          version={version}
          node={nodeForm || undefined}
          context={context}
          onClose={() => setNodeForm(undefined)}
          onSaved={(row) => {
            setNodeForm(undefined);
            void saved(row);
          }}
        />
      )}
      {nodeDetail && version && (
        <Modal title={nodeDetail.name} onClose={() => setNodeDetail(undefined)}>
          <div className="flex flex-wrap gap-2 text-12 text-secondary">
            <span>{nodeKinds[nodeDetail.kind]}</span>
            <span>· {flowStatuses[version.flow_state[nodeDetail.id]?.status]}</span>
            <span>· {context?.members.find((member) => member.id === nodeDetail.owner_id)?.name || "手动分派"}</span>
          </div>
          {nodeDetail.depends_on.length > 0 && (
            <p className="text-13 text-secondary">
              前置：
              {nodeDetail.depends_on.map((id) => version.flow_nodes.find((node) => node.id === id)?.name).join("、")}（
              {nodeDetail.join === "all" ? "全部完成" : "任一完成"}）
            </p>
          )}
          {version.flow_state[nodeDetail.id]?.notice && (
            <p className="text-13 text-warning-primary">{version.flow_state[nodeDetail.id].notice}</p>
          )}
          {writable && !finished && !version.automation_enabled && (
            <Button
              variant="neutral-primary"
              onClick={() => {
                setNodeForm(nodeDetail);
                setNodeDetail(undefined);
              }}
            >
              编辑节点与负责人
            </Button>
          )}
          {nodeDetail.kind !== "milestone" ? (
            <Button
              variant="neutral-primary"
              onClick={() => {
                openRecord(nodeDetail.kind as LinkedRecordKind, nodeDetail.object_id!);
                setNodeDetail(undefined);
              }}
            >
              查看 / 处理{nodeKinds[nodeDetail.kind]}
            </Button>
          ) : (
            writable &&
            !finished && (
              <Button
                variant="neutral-primary"
                onClick={() =>
                  setAction(version.flow_state[nodeDetail.id]?.manual_completed ? "reopen_node" : "complete_node")
                }
              >
                {version.flow_state[nodeDetail.id]?.manual_completed ? "重开里程碑" : "确认里程碑完成"}
              </Button>
            )
          )}
        </Modal>
      )}
      {action && version && (
        <Modal
          title={
            action === "enable_automation"
              ? "启用自动流转"
              : action === "disable_automation"
                ? "切换跟踪模式"
                : action === "advance"
                  ? "推进版本阶段"
                  : action === "back"
                    ? "退回上一阶段"
                    : action === "cancel"
                      ? "取消版本"
                      : "确认里程碑"
          }
          onClose={() => setAction(undefined)}
          onSubmit={async (actionForm) => {
            const row = await qualityApi.write<VersionDetail>(`${base}versions/${version.id}/workflow/`, {
              action,
              expected_version: version.edit_version,
              note: actionForm.get("note"),
              ...(nodeDetail ? { node_id: nodeDetail.id } : {}),
            });
            setAction(undefined);
            setNodeDetail(undefined);
            await saved(row);
          }}
        >
          {action === "enable_automation" && (
            <p className="text-13 leading-6 text-secondary">
              满足前置条件后自动分派。已有其他负责人时暂停；验收与发布仍需人工确认。
            </p>
          )}
          <Field label="处理说明 *">
            <textarea name="note" required maxLength={4000} rows={3} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </main>
  );
}
