import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { useCollectionPagination } from "@/components/quality/use-collection-pagination";
// SPDX-License-Identifier: AGPL-3.0-only
import { useLocation } from "react-router";
import { ownerRecordHref, ownerStatisticsScope } from "@/components/quality/owner-statistics";
import { OwnerSummary } from "@/components/quality/owner-summary";
import { periodOwnerMetrics } from "@/components/quality/owner-metrics";
import { observer } from "mobx-react";
import useSWR from "swr";
import { useParams, useSearchParams } from "react-router";
import { Button } from "@plane/ui";
import { getDate, renderFormattedDate } from "@plane/utils";
import { useProject } from "@/hooks/store/use-project";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Modal, Paging, fieldClass } from "@/components/quality/shared";
import { Distribution, TrendChart } from "@/components/quality/statistics-display";
import { resultNames, planStatusNames, statusNames } from "@/components/quality/types";
import type { ProjectReport, Workload } from "./project-period-types";
import { reportMetrics } from "./project-period-types";

const day = (value: Date) =>
  `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
const total = (values: Record<string, number>) => Object.values(values).reduce((sum, count) => sum + count, 0);
const names: Record<string, string> = {
  unexecuted: "待执行",
  backlog: "待排期",
  unstarted: "待开发",
  started: "开发中",
  ...planStatusNames,
  ...statusNames,
};
const colors: Record<string, string> = {
  started: "text-accent-primary",
  running: "text-accent-primary",
  in_progress: "text-accent-primary",
  paused: "text-secondary",
  completed: "text-success-primary",
  closed: "text-success-primary",
  cancelled: "text-secondary",
  resolved: "text-warning-primary",
  open: "text-warning-primary",
  returned: "text-danger-primary",
};

export const ProjectPeriodReport = observer(function ProjectPeriodReport() {
  const { workspaceSlug } = useParams();
  const location = useLocation();
  const { joinedProjectIds, getProjectById } = useProject();
  const [params, setParams] = useSearchParams();
  // Compute calendar ranges in the same China date used by the report query.
  const today = getDate(renderFormattedDate(new Date(), "yyyy-MM-dd"))!;
  const projectId = params.get("project") || joinedProjectIds?.[0] || "";
  const start = params.get("start") || day(new Date(today.getFullYear(), today.getMonth(), 1));
  const end = params.get("end") || day(today);
  const tz = "Asia/Shanghai";
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/project-report/`;
  const query = new URLSearchParams({ start, end, timezone: tz });
  const { data, error, isLoading } = useSWR(projectId ? `${base}?${query}` : null, (url: string) =>
    qualityApi.read<ProjectReport>(url)
  );
  const detailMetric = params.get("report_detail");
  const detail = detailMetric
    ? {
        title: params.get("report_title") || "报表明细",
        query: Object.fromEntries(
          [...params].filter(([key]) => key.startsWith("report_filter_")).map(([key, value]) => [key.slice(14), value])
        ) as Record<string, string>,
      }
    : undefined;
  const setDetail = (next: { title: string; query: Record<string, string> } | undefined) => {
    const values = new URLSearchParams(params);
    for (const key of [...values.keys()].filter((name) => name.startsWith("report_"))) values.delete(key);
    if (next) {
      values.set("report_detail", next.query.detail || "workload");
      values.set("report_title", next.title);
      for (const [key, value] of Object.entries(next.query)) values.set(`report_filter_${key}`, value);
    }
    setParams(values, { replace: true, preventScrollReset: true });
  };
  const detailPagination = useCollectionPagination(`${base}:${query}:${JSON.stringify(detail)}`);
  const detailQuery = new URLSearchParams({
    ...Object.fromEntries(query),
    ...detail?.query,
    page: String(detailPagination.page),
    per_page: String(detailPagination.perPage),
  });
  const { data: records, error: detailError } = useSWR(detail ? `${base}?${detailQuery}` : null, (url: string) =>
    qualityApi.read<{
      count: number;
      results: { id: string; title: string; path: string; kind: string; result?: string }[];
    }>(url)
  );
  const show = (title: string, filter: Record<string, string>) => {
    detailPagination.paging.onChange(1);
    setDetail({ title, query: filter });
  };
  const apply = (values: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) next.set(key, value);
    for (const key of [...next.keys()].filter((name) => name.startsWith("report_") || name.startsWith("owner_")))
      next.delete(key);
    setParams(next);
  };
  const quick = (kind: string) => {
    const from = new Date(today);
    if (kind === "month") from.setDate(1);
    else if (kind === "week") from.setDate(from.getDate() - ((from.getDay() + 6) % 7));
    else from.setDate(from.getDate() - 29);
    apply({ start: day(from), end: day(today) });
  };
  const projectUrl = `/${workspaceSlug}/projects/${projectId}`;
  const members = data
    ? [...data.workload, data.unassigned].filter(
        (row) => total(row.work) + total(row.plans) + total(row.defects) + row.period_executions > 0
      )
    : [];
  const workloadCell = (row: Workload, resource: "work" | "plans" | "defects") => (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(row[resource])
        .filter(([, count]) => count > 0)
        .map(([status, count]) => (
          <button
            key={status}
            type="button"
            onClick={() =>
              show(`${row.name} · ${names[status] || status}`, {
                detail: "workload",
                resource,
                status,
                assignee_id: row.user_id,
              })
            }
            className={`rounded border border-subtle px-2 py-1 text-11 hover:bg-layer-1 ${colors[status] || "text-warning-primary"}`}
          >
            {names[status] || status} {count}
          </button>
        ))}
      {total(row[resource]) === 0 && <span className="text-tertiary">—</span>}
    </div>
  );
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-20 font-semibold">项目工作报表</h1>
      </div>
      <form
        key={`${projectId}:${start}:${end}:${tz}`}
        className="flex flex-wrap items-end gap-3 rounded-md border border-subtle bg-surface-1 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          apply({
            project: String(form.get("project")),
            start: String(form.get("start")),
            end: String(form.get("end")),
            timezone: "Asia/Shanghai",
          });
        }}
      >
        <label className="min-w-40 flex-1 space-y-1 text-12 text-secondary">
          <span>项目</span>
          <select
            key={`${projectId}:${joinedProjectIds?.length}`}
            name="project"
            className={fieldClass}
            defaultValue={projectId}
          >
            {joinedProjectIds?.map((id) => (
              <option key={id} value={id}>
                {getProjectById(id)?.name || "项目"}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-12 text-secondary">
          <span>开始日期</span>
          <input name="start" aria-label="开始日期" className={fieldClass} type="date" required defaultValue={start} />
        </label>
        <label className="space-y-1 text-12 text-secondary">
          <span>结束日期</span>
          <input name="end" aria-label="结束日期" className={fieldClass} type="date" required defaultValue={end} />
        </label>

        <Button type="submit">应用</Button>
        <div className="flex gap-1">
          {[
            ["week", "本周"],
            ["month", "本月"],
            ["30", "近30天"],
          ].map(([key, title]) => (
            <button
              type="button"
              key={key}
              className="rounded px-2 py-2 text-12 text-secondary hover:bg-layer-1"
              onClick={() => quick(key)}
            >
              {title}
            </button>
          ))}
        </div>
      </form>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {isLoading && (
        <p role="status" className="text-13 text-secondary">
          正在汇总项目数据…
        </p>
      )}
      {data && (
        <>
          <div className="flex flex-wrap justify-between gap-2 text-12 text-secondary">
            <span>
              {data.project.name} · {data.start.replaceAll("-", "/")} — {data.end.replaceAll("-", "/")}
            </span>
            <span>区间统计</span>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {reportMetrics.map((metric) => (
              <button
                type="button"
                key={metric.key}
                className="rounded-md border border-subtle p-4 text-left hover:bg-layer-1"
                onClick={() => show(metric.name, { detail: metric.key })}
              >
                <p className="text-12 text-secondary">{metric.name}</p>
                <p className={`my-2 text-24 font-semibold tabular-nums ${metric.color}`}>
                  {data.activity[metric.key] || 0}
                </p>
                <p className="text-11 leading-5 text-tertiary">{metric.note}</p>
              </button>
            ))}
          </div>
          <TrendChart
            title="区间变化"
            data={data.trend.map((row) => ({ ...row, key: row.date, name: row.date.replaceAll("-", "/") }))}
            series={[
              { key: "work_created", label: "新增工作项", color: "#4b86c6" },
              { key: "test_executions", label: "测试执行", color: "#8d78b6" },
              { key: "manual_executions", label: "人工验证", color: "#4b9b96" },
              { key: "defects_created", label: "新增缺陷", color: "#db8650" },
              { key: "defects_closed", label: "关闭缺陷", color: "#379b76" },
            ]}
          />
          <div className="grid gap-4 lg:grid-cols-2">
            <Distribution
              title="区间测试结果"
              rows={Object.keys(resultNames)
                .filter((key) => key !== "pending")
                .map((key, i) => ({
                  key,
                  name: resultNames[key],
                  count: data.test_results[key] || 0,
                  color: ["#379b76", "#c94c5c", "#db8650", "#b6a05c", "#8b9ba8"][i],
                }))}
              onSelect={(result) => show(`测试执行 · ${resultNames[result]}`, { detail: "test_executions", result })}
            />
            {data.manual_results && (
              <Distribution
                title="区间人工验证结果"
                rows={Object.keys(resultNames)
                  .filter((key) => key !== "pending")
                  .map((key, i) => ({
                    key,
                    name: resultNames[key],
                    count: data.manual_results?.[key] || 0,
                    color: ["#379b76", "#c94c5c", "#db8650", "#b6a05c", "#8b9ba8"][i],
                  }))}
                onSelect={(result) =>
                  show(`人工验证 · ${resultNames[result]}`, { detail: "manual_executions", result })
                }
              />
            )}
            <section className="space-y-4 rounded-md border border-subtle p-4">
              <h2 className="text-14 font-medium">当前待办</h2>
              <p className="text-12 text-secondary">当前未完成记录，不受日期范围限制。</p>
              {[
                ["工作项", data.current.work_unfinished, "current_work"],
                ["待执行或待确认计划", data.current.plans_unfinished, "current_plans"],
                ["未关缺陷", data.current.defects_unclosed, "current_defects"],
              ].map(([title, count, metric]) => (
                <button
                  type="button"
                  key={String(title)}
                  onClick={() => show(String(title), { detail: String(metric) })}
                  className="flex w-full items-center justify-between border-t border-subtle py-3 text-13"
                >
                  <span>{title}</span>
                  <strong className="text-18 text-accent-primary">{count} →</strong>
                </button>
              ))}
            </section>
          </div>
          <OwnerSummary
            endpoint={base.replace(/project-report\/$/, "owner-statistics/")}
            source="period"
            params={query}
            metrics={periodOwnerMetrics}
          />
          <section className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-16 font-semibold">人员负载</h2>
              <span className="text-12 text-secondary">当前待办 · 点击数量查看</span>
            </div>
            <div className="overflow-x-auto rounded-md border border-subtle">
              <table className="w-full min-w-[880px] text-left text-12">
                <thead className="bg-layer-1 text-secondary">
                  <tr>
                    {["人员 / 项目职责", "工作项", "测试计划", "缺陷", "区间执行"].map((label) => (
                      <th key={label} className="p-3 font-medium">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {members.map((row) => (
                    <tr key={row.user_id} className="border-t border-subtle align-top">
                      <td className="p-3">
                        <p className="font-medium">{row.name}</p>
                        <p className="mt-1 text-11 text-secondary">{row.role}</p>
                      </td>
                      <td className="p-3">{workloadCell(row, "work")}</td>
                      <td className="p-3">{workloadCell(row, "plans")}</td>
                      <td className="p-3">{workloadCell(row, "defects")}</td>
                      <td className="p-3 tabular-nums">
                        <button
                          type="button"
                          className="text-accent-primary hover:underline"
                          onClick={() => {
                            const next = new URLSearchParams(params);
                            next.set(
                              "owner_scope",
                              ownerStatisticsScope(
                                base.replace(/project-report\/$/, "owner-statistics/"),
                                "period",
                                query
                              )
                            );
                            next.set("owner_metric", "test_executions");
                            next.set("owner_id", row.user_id);
                            next.set("owner_name", row.name);
                            next.set("owner_detail_page", "1");
                            next.delete("owner_status");
                            setParams(next, { replace: true, preventScrollReset: true });
                          }}
                        >
                          {row.period_executions}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {members.length === 0 && <p className="p-5 text-13 text-secondary">当前没有待办或区间执行记录。</p>}
            </div>
          </section>
          <details className="text-12 text-secondary">
            <summary className="cursor-pointer">统计口径</summary>
            <div className="mt-3 space-y-2">
              {data.definitions.map((text) => (
                <p key={text}>{text}</p>
              ))}
            </div>
          </details>
        </>
      )}
      {detail && (
        <Modal title={detail.title} width="wide" onClose={() => setDetail(undefined)}>
          {detailError && (
            <p role="alert" className="text-danger-primary">
              {errorMessage(detailError)}
            </p>
          )}
          {!records && !detailError && <p>正在读取明细…</p>}
          {records && (
            <>
              <div className="space-y-2">
                {records.results.map((row) => (
                  <Link
                    key={row.id}
                    to={ownerRecordHref(`${projectUrl}/${row.path}`, location.pathname + location.search)}
                    className="flex items-center justify-between rounded border border-subtle p-3 text-13 hover:bg-layer-1"
                  >
                    <span>{row.title}</span>
                    <span className="ml-3 shrink-0 text-12 text-secondary">
                      {row.result ? resultNames[row.result] : row.kind} →
                    </span>
                  </Link>
                ))}
                {!records.count && <p className="py-6 text-13 text-secondary">此范围没有记录。</p>}
              </div>
              <Paging {...detailPagination.paging} count={records.count} />
            </>
          )}
        </Modal>
      )}
    </div>
  );
});
