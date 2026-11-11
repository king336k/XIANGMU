import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { projectDutySummary } from "./duty-summary";
import { renderNumericDateTime } from "@plane/utils";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useSearchParams, Navigate, useParams, useLocation } from "react-router";
import { Beaker, Bug, ClipboardList, FileCheck, Plus, RefreshCw, Link2 } from "lucide-react";
import { Button, getButtonStyling } from "@plane/ui";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";
import { PageHead } from "@/components/core/page-title";
import { qualityApi, errorMessage } from "./api";
import { CaseHistory } from "./case-history";
import { CaseListActions } from "./case-list-actions";
import { CaseForm } from "./case-form";
import { DefectQuickEdit } from "./defect-quick-edit";
import { DefectForm } from "./defect-form";
import { SourceForm } from "./source-form";
import { BulkActionsBar } from "./bulk-actions-bar";
import { movedSettingsPath } from "@/components/settings/management-paths";
import { FieldResourcesPanel } from "./field-resources-panel";
import {
  defectDisplayTitle,
  can,
  canOpenQualityTab,
  severityNames,
  priorityNames,
  planStatusNames,
  resultNames,
  statusNames,
} from "./types";
import { SavedViewControls } from "./saved-view-controls";
import { LayoutControls, recordLayout } from "./layout-controls";
import { RecordPresentation } from "./record-presentation";
import { TaskPackageForm } from "./task-package-form";
import { ImportForm } from "./import-form";
import { ReportsPanel } from "./reports-panel";
import { PlanForm } from "./plan-form";
import { PlanDetail } from "./plan-detail";
import { ListFilters } from "./list-filters";
import { pageSize, normalizedPageParams } from "./pagination";
import { DefectStatistics } from "./defect-statistics";
import { Empty, Paging, Modal } from "./shared";
import { CaseList, PlanList, ExecutionList, DefectList } from "./record-lists";
import { AssetsPanel } from "./assets-panel";
import type { Suite, Release } from "./assets-panel";
import { QualitySummary } from "./quality-summary";
import type { Context, Defect, Execution, Page, Plan, Report, TestCase } from "./types";

const tabs = [
  { key: "cases", name: "测试用例", group: "assets" },
  { key: "suites", name: "用例集", group: "assets" },
  { key: "plans", name: "测试计划", group: "execution" },
  { key: "executions", name: "执行记录", group: "execution" },
  { key: "report", name: "测试报告", group: "results" },
  { key: "overview", name: "测试概览", group: "results" },
  { key: "resources", name: "测试资源", group: "settings" },
];
const groups = [
  { key: "execution", name: "测试任务", tab: "plans", icon: Beaker },
  { key: "assets", name: "用例库", tab: "cases", icon: ClipboardList },
  { key: "results", name: "测试结果", tab: "report", icon: FileCheck },
];

export function QualityWorkbench({ defectsOnly = false }: { defectsOnly?: boolean }) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const canonicalParams = useParams();
  const { mutate: mutateCache } = useSWRConfig();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const tab = defectsOnly
    ? params.get("panel") === "statistics"
      ? "defect-statistics"
      : "defects"
    : tabs.some((t) => t.key === params.get("tab")) ||
        ["roles", "integrations", "releases"].includes(params.get("tab") || "")
      ? params.get("tab")!
      : "plans";
  const group = tabs.find((item) => item.key === tab)?.group;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/`;
  const projectUrl = `/${workspaceSlug}/projects/${projectId}`;
  const {
    data: context,
    error: contextError,
    mutate: refreshContext,
  } = useSWR(`${base}context/`, (url: string) => qualityApi.read<Context>(url));
  const tabAllowed = canOpenQualityTab(context, tab);
  const {
    data: collection,
    error,
    isLoading,
    mutate,
  } = useSWR(
    tabAllowed && !["report", "roles", "resources", "integrations", "overview", "defect-statistics"].includes(tab)
      ? `${base}${tab}/?${normalizedPageParams(params).toString()}`
      : null,
    (url: string) => qualityApi.read<Page<TestCase | Plan | Execution | Defect | Suite | Release>>(url)
  );
  const {
    data: report,
    error: reportError,
    mutate: refreshReport,
  } = useSWR(tabAllowed ? `${base}report/` : null, (url: string) => qualityApi.read<Report>(url));
  const [form, setForm] = useState<"case" | "plan" | "defect" | "source" | "import" | "task-package" | null>(null);
  const [caseRead, setCaseRead] = useState<{ value: TestCase; history: boolean }>();
  const [selectedCases, setSelectedCases] = useState<TestCase[]>([]);
  const deletedScope = params.get("deleted");
  const archivedScope = params.get("archived");
  useEffect(() => setSelectedCases([]), [projectId, deletedScope, archivedScope]);
  const [caseValue, setCaseValue] = useState<TestCase>();
  const [copyCase, setCopyCase] = useState(false);
  const [defectEntryMode, setDefectEntryMode] = useState<"details" | "workflow">();
  const [quickEdit, setQuickEdit] = useState<{ value: Defect; field: "severity" | "assignee" }>();
  const [defectValue, setDefectValue] = useState<Defect>();
  useEffect(() => {
    if (defectsOnly && params.get("create") === "1") {
      setDefectEntryMode(undefined);
      setDefectValue(undefined);
      setForm("defect");
      const next = new URLSearchParams(params);
      next.delete("create");
      setParams(next, { replace: true });
    }
  }, [defectsOnly, params, setParams]);
  const { data: linkedDefect } = useSWR(
    defectsOnly && params.get("defect") ? `${base}defects/${params.get("defect")}/` : null,
    (url: string) => qualityApi.read<Defect>(url)
  );
  const [plan, setPlan] = useState<Plan | null>(null);
  const { data: linkedPlan } = useSWR(
    !defectsOnly && params.get("plan") ? `${base}plans/${params.get("plan")}/` : null,
    (url: string) => qualityApi.read<Plan>(url)
  );
  const { data: linkedCase } = useSWR(
    !defectsOnly && params.get("case") ? `${base}cases/${params.get("case")}/` : null,
    (url: string) => qualityApi.read<TestCase>(url)
  );
  useEffect(() => {
    if (linkedCase) setCaseRead({ value: linkedCase, history: false });
  }, [linkedCase]);
  const activePlan = plan || linkedPlan;
  const [actionError, setActionError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const saved = async () => {
    await mutateCache((key) => typeof key === "string" && key.startsWith(`${base}defect-statistics/`));
    await mutate();
    await refreshReport();
    await refreshContext();
  };
  const switchTab = (key: string) => {
    setParams({ tab: key });
    setPlan(null);
    setMessage("");
    setActionError("");
  };
  const createDefect = async (execution: Execution) => {
    setBusy(true);
    setActionError("");
    try {
      await qualityApi.write(`${base}executions/${execution.id}/defect/`, {});
      setMessage("缺陷已创建或已关联，请进入缺陷管理查看。");
      await refreshReport();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const visible = collection?.results ?? [];
  const layout = recordLayout(params);
  const records = visible.map((row) => {
    if ("severity" in row)
      return {
        id: row.id,
        code: row.code,
        title: defectDisplayTitle(row.title),
        subtitle: `${row.source_kind === "daq" ? "DAQ 上报" : row.source_kind === "test" ? "测试提报" : "平台新建"} · ${row.source_kind === "daq" ? "采集员" : "创建人"}：${row.created_by_name || "未记录"}${row.created_at ? " · " + renderNumericDateTime(row.created_at) : ""}`,
        status: row.status,
        statusName: statusNames[row.status] || row.status,
        severity: row.severity,
        values: [severityNames[row.severity], row.assignee_name || "未指派", row.affected_build || "未填写"],
      };
    if ("steps" in row)
      return {
        id: row.id,
        code: row.code,
        title: row.title,
        subtitle: `v${row.version} · ${row.steps.length} 个步骤 · 创建人：${row.created_by_name || "未记录"}`,
        status: row.module || "none",
        statusName: row.module || "未分模块",
        values: [priorityNames[row.priority], row.requirement_title || "未关联工作项", `v${row.version}`],
      };
    if ("summary" in row)
      return {
        id: row.id,
        code: row.code,
        title: row.name,
        subtitle: `${row.build} · ${row.environment} · 创建人：${row.created_by_name || "未记录"}`,
        status: row.managed ? row.status : "ordinary",
        statusName: row.managed ? planStatusNames[row.status] || row.status : "普通计划",
        values: [
          row.assignee_name || "未指派",
          `${row.summary.executed}/${row.summary.total} 已执行`,
          `${row.summary.failed} 失败 · ${row.summary.inconclusive || 0} 无法判定`,
        ],
      };
    if ("result" in row)
      return {
        id: row.id,
        code: row.code,
        title: row.case_title,
        subtitle: row.plan_name,
        status: row.result,
        statusName: resultNames[row.result],
        values: [row.executor || "成员", row.build, row.actual_result || "无补充说明"],
      };
    return {
      id: row.id,
      code: row.code,
      title: row.name,
      subtitle: `创建人：${row.created_by_name || "未记录"}`,
      status: "status" in row ? row.status : row.published ? "published" : "draft",
      statusName:
        "status" in row ? (row.status === "admitted" ? "检查通过" : "待检查") : row.published ? "已发布" : "草稿",
      values: ["edit_version" in row ? `v${row.edit_version}` : "", "", ""],
    };
  });
  const present = ["defects", "plans", "executions", "cases"].includes(tab) && (tab === "defects" || layout !== "list");
  const [viewExecution, setViewExecution] = useState<Execution>();
  const openRecord = (id: string) => {
    const row = visible.find((value) => value.id === id);
    if (!row) return;
    if ("severity" in row) {
      setDefectEntryMode(undefined);
      setDefectValue(row);
      setForm("defect");
    } else if ("steps" in row) {
      setCaseRead({ value: row, history: false });
    } else if ("summary" in row) setPlan(row);
    else if ("result" in row) setViewExecution(row);
  };
  const failed = contextError || error || (tab === "report" && reportError);
  const movedTo =
    !defectsOnly &&
    context?.identifier &&
    workspaceSlug &&
    projectId &&
    ["roles", "integrations", "releases"].includes(tab)
      ? movedSettingsPath(workspaceSlug, context.identifier, projectId, tab, params)
      : undefined;
  if (movedTo && tabAllowed) return <Navigate replace to={`${movedTo}${location.hash}`} />;

  if (context && !tabAllowed)
    return (
      <div className="p-5 text-13">
        <p role="alert" className="text-secondary">
          当前账号没有此功能权限。
        </p>
        <Link className="mt-3 inline-block text-accent-primary" to={`${projectUrl}/quality/?tab=plans`}>
          返回测试计划
        </Link>
      </div>
    );
  if (
    canonicalParams.projectId &&
    context?.identifier &&
    canonicalParams.projectId.toLowerCase() !== context.identifier.toLowerCase()
  )
    return (
      <Navigate
        replace
        to={`/${workspaceSlug}/p/${encodeURIComponent(context.identifier)}/${defectsOnly ? "defects" : "quality"}/?${params}`}
      />
    );
  return (
    <div className="platform-workspace flex h-full min-h-0 min-w-0 flex-col bg-surface-1">
      <PageHead title={`${context?.project_name ?? "项目"} · ${defectsOnly ? "缺陷" : "测试"}`} />
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2">
          <AppSidebarToggleButton onlyWhenCollapsed />
          <span className="text-13 text-secondary">{context?.project_name ?? "项目"}</span>
          {context?.business_roles_enabled && (
            <span className="rounded border border-subtle px-2 py-0.5 text-11 text-secondary">
              {projectDutySummary(context.business_role_name.split("、")).label}
            </span>
          )}
          <span className="text-tertiary">/</span>
          {defectsOnly ? <Bug className="size-4" /> : <Beaker className="size-4" />}
          <h1 className="platform-page-title">{defectsOnly ? "缺陷" : "测试"}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!["roles", "resources", "integrations", "overview", "report", "defect-statistics"].includes(tab) && (
            <>
              {context && <ListFilters compact kind={tab} context={context} params={params} onApply={setParams} />}
              <SavedViewControls kind={tab} params={params} onApply={setParams} />
              <LayoutControls params={params} onApply={setParams} />
            </>
          )}
          {context && can(context, "manage_test_plan") && tab === "plans" && (
            <Button variant="neutral-primary" onClick={() => setForm("task-package")}>
              导入任务包
            </Button>
          )}
          {context && can(context, "manage_case") && tab === "cases" && (
            <Button variant="neutral-primary" onClick={() => setForm("import")}>
              导入用例
            </Button>
          )}
          <Link
            className={getButtonStyling("neutral-primary", "md", false)}
            to={`${projectUrl}/${defectsOnly ? "quality" : "defects"}`}
          >
            {defectsOnly ? "进入测试" : "查看缺陷"}
          </Link>
          {!defectsOnly && (
            <Button variant="neutral-primary" onClick={() => switchTab("resources")}>
              测试资源
            </Button>
          )}
          {context?.identifier && (
            <Button
              variant="neutral-primary"
              size="sm"
              aria-label="复制项目短链接"
              title="复制项目短链接"
              onClick={async () => {
                try {
                  const query = new URLSearchParams(params);
                  await navigator.clipboard.writeText(
                    `${window.location.origin}/${workspaceSlug}/p/${encodeURIComponent(context.identifier)}/${defectsOnly ? "defects" : "quality"}/${query.size ? `?${query}` : ""}`
                  );
                  setMessage("短链接已复制");
                } catch {
                  setActionError("复制失败，请重试。");
                }
              }}
            >
              <Link2 className="size-3.5" />
            </Button>
          )}
          <Button variant="neutral-primary" aria-label="刷新数据" onClick={() => void saved()}>
            <RefreshCw className="size-4" />
          </Button>
          {context &&
            can(context, defectsOnly ? "report" : tab === "cases" ? "manage_case" : "manage_test_plan") &&
            (tab === "cases" || tab === "plans" || defectsOnly) && (
              <Button
                onClick={() => {
                  setCaseValue(undefined);
                  setCopyCase(false);
                  setDefectEntryMode(undefined);
                  setDefectValue(undefined);
                  setForm(defectsOnly ? "defect" : tab === "cases" ? "case" : "plan");
                }}
              >
                <Plus className="mr-1 size-4" />
                {defectsOnly ? "提交缺陷" : tab === "cases" ? "新建用例" : "新建计划"}
              </Button>
            )}
        </div>
      </header>
      {!defectsOnly && (
        <>
          <nav aria-label="测试工作区" className="flex shrink-0 gap-6 overflow-x-auto border-b border-subtle px-5">
            {groups.map((item) => (
              <button
                key={item.key}
                aria-current={group === item.key ? "page" : undefined}
                onClick={() => switchTab(item.tab)}
                className={`flex shrink-0 items-center gap-2 border-b-2 py-3 text-13 ${group === item.key ? "border-accent-primary text-accent-primary" : "border-transparent text-secondary"}`}
              >
                <item.icon className="size-4" />
                {item.name}
              </button>
            ))}
          </nav>
          {group !== "settings" && (
            <nav
              aria-label="当前工作区内容"
              className="flex flex-wrap items-center gap-2 border-b border-subtle px-5 py-2"
            >
              {tabs
                .filter((item) => item.group === group)
                .map((item) => (
                  <button
                    key={item.key}
                    aria-current={tab === item.key ? "page" : undefined}
                    onClick={() => switchTab(item.key)}
                    className={`rounded-md px-3 py-1.5 text-12 ${tab === item.key ? "bg-layer-1 font-medium text-primary" : "text-secondary hover:bg-layer-1"}`}
                  >
                    {item.name}
                  </button>
                ))}
            </nav>
          )}
        </>
      )}
      {defectsOnly && (
        <nav aria-label="缺陷工作区" className="flex gap-6 border-b border-subtle px-5">
          {[
            { key: "list", name: "缺陷列表" },
            { key: "statistics", name: "统计报表" },
          ].map((item) => (
            <button
              key={item.key}
              type="button"
              aria-current={(params.get("panel") || "list") === item.key ? "page" : undefined}
              className={`border-b-2 py-3 text-13 ${(params.get("panel") || "list") === item.key ? "border-accent-primary text-accent-primary" : "border-transparent text-secondary"}`}
              onClick={() => {
                const next = new URLSearchParams(params);
                if (item.key === "list") next.delete("panel");
                else next.set("panel", item.key);
                next.delete("page");
                setParams(next);
              }}
            >
              {item.name}
            </button>
          ))}
        </nav>
      )}
      <main className="min-h-0 min-w-0 flex-1 overflow-auto p-3 sm:p-5">
        {failed && (
          <div
            role="alert"
            className="mb-4 flex items-center justify-between gap-3 rounded-md border border-subtle p-4 text-13 text-danger-primary"
          >
            <p>{errorMessage(failed)}</p>
            <Button variant="neutral-primary" onClick={() => void saved()}>
              重试
            </Button>
          </div>
        )}
        {actionError && (
          <p role="alert" className="mb-4 text-13 text-danger-primary">
            {actionError}
          </p>
        )}
        {message && (
          <p role="status" className="mb-4 text-13 text-success-primary">
            {message}{" "}
            <Link className="underline" to={`${projectUrl}/defects`}>
              查看缺陷
            </Link>
          </p>
        )}
        {!context && !contextError ? (
          <p role="status" className="text-13 text-secondary">
            正在加载项目权限…
          </p>
        ) : (
          context && (
            <>
              {activePlan && tab === "plans" ? (
                <PlanDetail
                  base={base}
                  value={activePlan}
                  canWrite={can(context, "execute")}
                  context={context}
                  onBack={() => {
                    setPlan(null);
                    const next = new URLSearchParams(params);
                    next.delete("plan");
                    setParams(next);
                  }}
                  onCopied={setPlan}
                  onSaved={saved}
                />
              ) : (
                <>
                  {(defectsOnly || ["cases", "plans", "suites"].includes(tab)) && (
                    <div
                      className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2"
                      aria-label="列表操作"
                    >
                      {defectsOnly && (
                        <nav aria-label="缺陷快捷视图" className="flex min-w-0 flex-wrap items-center gap-2">
                          {[
                            { key: "", name: "全部" },
                            { key: "unclosed", name: "未关闭" },
                            { key: "assigned_to_me", name: "指派给我" },
                            { key: "created_by_me", name: "由我创建" },
                            { key: "awaiting_regression", name: "待回归" },
                          ].map((item) => (
                            <button
                              type="button"
                              key={item.key}
                              aria-pressed={(params.get("view") || "") === item.key}
                              className={`rounded px-3 py-1.5 text-12 ${(params.get("view") || "") === item.key ? "bg-layer-1 font-medium text-primary" : "text-secondary hover:bg-layer-1"}`}
                              onClick={() => {
                                const next = new URLSearchParams(params);
                                if (item.key) next.set("view", item.key);
                                else next.delete("view");
                                next.delete("page");
                                setParams(next);
                              }}
                            >
                              {item.name}
                            </button>
                          ))}
                        </nav>
                      )}
                      {(tab === "cases" || tab === "suites"
                        ? can(context, "manage_case")
                        : tab === "plans"
                          ? can(context, "manage_test_plan")
                          : context.is_manager) &&
                        ["cases", "plans", "suites", "defects"].includes(tab) &&
                        visible.length > 0 && (
                          <div className="ml-auto flex shrink-0 items-center">
                            <BulkActionsBar
                              base={base}
                              kind={tab}
                              rows={visible.filter(
                                (row): row is TestCase | Plan | Suite | Defect =>
                                  ("title" in row || "name" in row) &&
                                  !("version" in row && typeof row.version === "string")
                              )}
                              deleted={params.get("deleted") === "true"}
                              archived={params.get("archived") === "true"}
                              onSaved={saved}
                            />
                          </div>
                        )}
                    </div>
                  )}
                  {tab === "defect-statistics" && (
                    <ListFilters kind="defects" context={context} params={params} onApply={setParams} />
                  )}
                  {tab === "defect-statistics" && (
                    <DefectStatistics
                      base={base}
                      params={params}
                      onFilter={(key, value) => {
                        const next = new URLSearchParams(params);
                        next.set(key, value);
                        next.delete("panel");
                        next.delete("page");
                        setParams(next);
                      }}
                    />
                  )}
                  {isLoading &&
                  !["report", "roles", "resources", "integrations", "overview", "defect-statistics"].includes(tab) ? (
                    <div role="status" className="space-y-3 py-6">
                      <p className="text-13 text-secondary">正在加载…</p>
                      <div className="h-12 animate-pulse rounded bg-layer-1" />
                      <div className="h-12 animate-pulse rounded bg-layer-1" />
                    </div>
                  ) : ![
                      "report",
                      "suites",
                      "releases",
                      "roles",
                      "resources",
                      "integrations",
                      "overview",
                      "defect-statistics",
                    ].includes(tab) &&
                    !visible.length &&
                    !(layout === "table" || (tab === "cases" && layout === "list")) ? (
                    <Empty>
                      {params.has("search") ||
                      [...params.keys()].some((key) => !["page", "tab", "per_page", "layout"].includes(key))
                        ? "没有匹配记录"
                        : tab === "cases"
                          ? "还没有测试用例"
                          : tab === "plans"
                            ? "还没有测试计划"
                            : tab === "executions"
                              ? "还没有执行记录"
                              : "还没有缺陷"}
                    </Empty>
                  ) : null}
                  {present && !isLoading && !failed && collection && (visible.length > 0 || layout === "table") && (
                    <RecordPresentation
                      kind={tab}
                      context={context}
                      layout={layout}
                      rows={records}
                      columns={
                        tab === "defects"
                          ? ["严重程度", "负责人", "影响版本"]
                          : tab === "cases"
                            ? ["优先级", "关联工作项", "版本"]
                            : tab === "plans"
                              ? ["负责人", "执行进度", "失败"]
                              : ["执行人", "版本", "实际结果"]
                      }
                      selectedIds={tab === "cases" ? selectedCases.map((row) => row.id) : undefined}
                      onToggle={
                        tab === "cases" && can(context, "manage_case") && !params.has("deleted")
                          ? (id, checked) => {
                              const item = visible.find((row) => row.id === id) as TestCase;
                              if (checked && selectedCases.length < 500) setSelectedCases([...selectedCases, item]);
                              else if (!checked) setSelectedCases(selectedCases.filter((row) => row.id !== id));
                            }
                          : undefined
                      }
                      onTogglePage={
                        tab === "cases" && can(context, "manage_case") && !params.has("deleted")
                          ? (checked) => {
                              const items = visible as TestCase[];
                              const ids = new Set(items.map((row) => row.id));
                              const rest = selectedCases.filter((row) => !ids.has(row.id));
                              if (checked && rest.length + items.length <= 500) setSelectedCases([...rest, ...items]);
                              else if (!checked) setSelectedCases(rest);
                            }
                          : undefined
                      }
                      canChangeStatus={
                        tab === "defects"
                          ? (id) => {
                              const row = visible.find((item) => item.id === id) as Defect | undefined;
                              return (
                                !!row &&
                                !row.archived_at &&
                                can(context, "manage_defect") &&
                                (context.is_manager || row.assignee_id === context.user_id)
                              );
                            }
                          : undefined
                      }
                      onStatusChange={
                        tab === "defects"
                          ? (id) => {
                              const row = visible.find((item) => item.id === id) as Defect;
                              if (row) {
                                setDefectEntryMode("workflow");
                                setDefectValue(row);
                                setForm("defect");
                              }
                            }
                          : undefined
                      }
                      onFieldChange={(id, field) => {
                        const row = visible.find((item) => item.id === id) as Defect;
                        if (row) setQuickEdit({ value: row, field });
                      }}
                      canChangeField={(id, field) => {
                        const row = visible.find((item) => item.id === id) as Defect | undefined;
                        return (
                          !!row &&
                          !row.archived_at &&
                          row.status !== "closed" &&
                          can(context, "manage_defect") &&
                          (field === "assignee"
                            ? context.is_manager
                            : context.is_manager || row.assignee_id === context.user_id)
                        );
                      }}
                      onOpen={openRecord}
                    />
                  )}
                  {tab === "cases" &&
                    context &&
                    can(context, "manage_case") &&
                    params.get("archived") !== "true" &&
                    params.get("deleted") !== "true" && (
                      <div className="mb-3">
                        <CaseListActions
                          base={base}
                          selected={selectedCases}
                          onSelection={(rows) => {
                            if (rows.length <= 500) setSelectedCases(rows);
                            else setMessage("最多选择500条用例，请缩小范围。");
                          }}
                          onSaved={saved}
                        />
                      </div>
                    )}
                  {!present && tab === "cases" && !isLoading && !failed && collection && (
                    <CaseList
                      rows={visible as TestCase[]}
                      base={base}
                      onSaved={saved}
                      context={context}
                      onView={(value) => setCaseRead({ value, history: false })}
                      onHistory={(value) => setCaseRead({ value, history: true })}
                      selected={selectedCases}
                      onSelection={
                        can(context, "manage_case") &&
                        params.get("archived") !== "true" &&
                        params.get("deleted") !== "true"
                          ? (rows) => {
                              if (rows.length <= 500) setSelectedCases(rows);
                              else setMessage("最多选择500条用例，请缩小范围。");
                            }
                          : undefined
                      }
                      projectUrl={projectUrl}
                      canWrite={can(context, "manage_case")}
                      onCopy={(value) => {
                        setCaseValue(value);
                        setCopyCase(true);
                        setForm("case");
                      }}
                      onEdit={(value) => {
                        setCopyCase(false);
                        setCaseValue(value);
                        setForm("case");
                      }}
                    />
                  )}
                  {!present && tab === "plans" && !!visible.length && (
                    <PlanList rows={visible as Plan[]} onSelect={setPlan} />
                  )}
                  {!present && tab === "executions" && !!visible.length && (
                    <ExecutionList
                      rows={visible as Execution[]}
                      canWrite={can(context, "report")}
                      busy={busy}
                      onDefect={createDefect}
                    />
                  )}
                  {!present && tab === "defects" && !!visible.length && (
                    <DefectList
                      rows={visible as Defect[]}
                      onEdit={(value) => {
                        setDefectValue(value);
                        setForm("defect");
                      }}
                    />
                  )}
                  {(tab === "suites" || tab === "releases") && (
                    <AssetsPanel
                      base={base}
                      kind={tab}
                      rows={visible as (Suite | Release)[]}
                      context={context}
                      onSaved={saved}
                      layout={layout}
                    />
                  )}
                  {tab === "resources" && <FieldResourcesPanel base={base} context={context} />}
                  {tab === "overview" && report && (
                    <QualitySummary
                      report={report}
                      onNavigate={(nextTab, result) => {
                        if (nextTab === "defects") window.location.assign(`${projectUrl}/defects/?view=unclosed`);
                        else {
                          setParams({ tab: nextTab, ...(result ? { result } : {}) });
                          setPlan(null);
                        }
                      }}
                    />
                  )}
                  {tab === "report" && <ReportsPanel base={base} context={context} />}
                  {!["report", "roles", "resources", "integrations", "overview", "defect-statistics"].includes(tab) &&
                    collection && (
                      <Paging
                        perPage={pageSize(params)}
                        onPageSizeChange={(size) => {
                          const next = new URLSearchParams(params);
                          next.set("per_page", String(size));
                          next.delete("page");
                          setParams(next);
                        }}
                        page={page}
                        count={collection.count}
                        onChange={(nextPage) => {
                          const next = new URLSearchParams(params);
                          next.set("page", String(nextPage));
                          setParams(next);
                        }}
                      />
                    )}
                </>
              )}
            </>
          )
        )}
      </main>
      {caseRead && (
        <CaseHistory
          base={base}
          value={caseRead.value}
          currentOnly={!caseRead.history}
          onClose={() => setCaseRead(undefined)}
        />
      )}
      {context && form === "case" && (
        <CaseForm
          base={base}
          context={context}
          value={caseValue}
          copy={copyCase}
          onClose={() => setForm(null)}
          onSaved={saved}
        />
      )}
      {viewExecution && (
        <Modal title="测试执行记录" onClose={() => setViewExecution(undefined)}>
          <ExecutionList
            rows={[viewExecution]}
            canWrite={!!context && can(context, "report")}
            busy={busy}
            onDefect={createDefect}
          />
        </Modal>
      )}
      {context && form === "plan" && (
        <PlanForm base={base} context={context} onClose={() => setForm(null)} onSaved={saved} />
      )}
      {quickEdit && context && (
        <DefectQuickEdit
          base={base}
          context={context}
          value={quickEdit.value}
          field={quickEdit.field}
          onClose={() => setQuickEdit(undefined)}
          onSaved={saved}
          projectUrl={projectUrl}
        />
      )}
      {context && (form === "defect" || (!!linkedDefect && defectsOnly)) && (
        <DefectForm
          key={`${(defectValue || linkedDefect)?.id || "new"}:${defectEntryMode || "view"}`}
          initialMode={defectEntryMode}
          onFromSource={() => setForm("source")}
          base={base}
          context={context}
          value={defectValue || linkedDefect}
          onClose={() => {
            setForm(null);
            setDefectEntryMode(undefined);
            const next = new URLSearchParams(params);
            next.delete("defect");
            setParams(next);
          }}
          onSaved={saved}
          projectUrl={projectUrl}
        />
      )}
      {context && form === "source" && <SourceForm base={base} onClose={() => setForm(null)} onSaved={saved} />}
      {context && form === "task-package" && (
        <TaskPackageForm base={base} onClose={() => setForm(null)} onSaved={saved} />
      )}
      {context && form === "import" && <ImportForm base={base} onClose={() => setForm(null)} onSaved={saved} />}
    </div>
  );
}
