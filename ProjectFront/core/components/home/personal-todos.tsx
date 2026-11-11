import { useState } from "react";
import useSWR from "swr";
import { renderFormattedDate } from "@plane/utils";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { qualityApi, errorMessage } from "../quality/api";
import { Badge } from "../quality/record-badge";
import { Paging, fieldClass } from "../quality/shared";

export type PersonalTodo = {
  id: string;
  title: string;
  kind: string;
  kind_name: string;
  status: string;
  code: string;
  project_name: string;
  responsibility: string;
  next_action: string;
  due_date: string | null;
  url: string;
};
const groups = {
  "": "全部类型",
  task: "研发任务",
  requirement: "需求",
  defect: "缺陷",
  solution: "方案审核",
  plan: "测试计划",
};
const stateNames: Record<string, string> = {
  draft: "草稿",
  approved: "已确认",
  backlog: "待排期",
  unstarted: "未开始",
  started: "处理中",
  pending: "待安排",
  ready: "待开始",
  running: "执行中",
  paused: "已暂停",
  review: "待审核",
  returned: "待复测",
  open: "待处理",
  in_progress: "处理中",
  resolved: "待验证",
};
export function PersonalTodoList({
  rows,
  count,
  page,
  perPage,
  onPageChange,
  onPageSizeChange,
  isLoading,
  error,
}: {
  rows: PersonalTodo[];
  count: number;
  page: number;
  perPage: number;
  onPageChange: (value: number) => void;
  onPageSizeChange: (value: number) => void;
  isLoading?: boolean;
  error?: string;
}) {
  if (error)
    return (
      <p role="alert" className="py-3 text-13 text-danger-primary">
        {error}
      </p>
    );
  if (isLoading)
    return (
      <p role="status" className="py-3 text-13 text-secondary">
        正在读取待办…
      </p>
    );
  if (!rows.length)
    return (
      <p role="status" className="py-3 text-13 text-secondary">
        暂无待办
      </p>
    );
  return (
    <>
      <ul className="divide-y divide-subtle">
        {rows.map((row) => (
          <li key={`${row.kind}-${row.id}`}>
            <Link
              to={row.url}
              className="focus-visible:outline-accent-strong-1 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 rounded py-3 hover:bg-layer-1 focus-visible:outline-2 focus-visible:outline-offset-2 sm:px-2"
            >
              <div className="min-w-0 flex-1 basis-52">
                <div className="flex min-w-0 items-start gap-2 text-13">
                  <span className="shrink-0 text-12 text-secondary">{row.code || row.kind_name}</span>
                  <span className="font-medium break-words text-accent-primary">{row.title}</span>
                </div>
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-12 text-secondary">
                  <span>{row.project_name}</span>
                  <span>{row.kind_name}</span>
                  <span>{row.responsibility}</span>
                  {row.due_date && <span>截止 {renderFormattedDate(row.due_date)}</span>}
                </p>
              </div>
              <Badge
                value={
                  ({ started: "in_progress", unstarted: "ready", backlog: "pending" } as Record<string, string>)[
                    row.status
                  ] || row.status
                }
                label={stateNames[row.status] || "待处理"}
              />
              <span className="text-12 text-accent-primary">{row.next_action} →</span>
            </Link>
          </li>
        ))}
      </ul>
      <Paging
        page={page}
        count={count}
        perPage={perPage}
        pageSizes={[5, 10, 20, 50]}
        onChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </>
  );
}
export function PersonalTodos({ workspaceSlug }: { workspaceSlug: string }) {
  const [filters, setFilters] = useState({ kind: "", search: "", page: 1, perPage: 5 });
  const params = new URLSearchParams({
    workspace: workspaceSlug,
    search: filters.search,
    page: String(filters.page),
    per_page: String(filters.perPage),
  });
  if (filters.kind) params.set("kind", filters.kind);
  const { data, error, isLoading, mutate } = useSWR(
    `/api/quality-auth/my-todos/?${params}`,
    (url: string) => qualityApi.read<{ count: number; results: PersonalTodo[] }>(url),
    { refreshInterval: 60000 }
  );
  return (
    <section
      aria-label="我的待办"
      className="platform-record-section min-w-0 rounded-lg border border-subtle bg-surface-1 p-4 sm:p-5"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-16 font-semibold">
          我的待办{data ? <span className="font-normal ml-2 text-12 text-secondary">{data.count}</span> : null}
        </h2>
        <div className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_7rem] items-center gap-2 sm:w-72">
          <input
            type="search"
            aria-label="搜索待办"
            placeholder="编号或标题"
            maxLength={160}
            value={filters.search}
            className={`${fieldClass} h-8 min-w-0 text-12`}
            onChange={(event) => setFilters({ ...filters, search: event.target.value, page: 1 })}
          />
          <select
            aria-label="待办类型"
            value={filters.kind}
            className={`${fieldClass} h-8 text-12`}
            onChange={(event) => setFilters({ ...filters, kind: event.target.value, page: 1 })}
          >
            {Object.entries(groups).map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </select>
          {error && (
            <button type="button" className="text-12 text-accent-primary" onClick={() => void mutate()}>
              重试
            </button>
          )}
        </div>
      </div>
      <PersonalTodoList
        rows={data?.results || []}
        count={data?.count || 0}
        page={filters.page}
        perPage={filters.perPage}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        onPageChange={(page) => setFilters({ ...filters, page })}
        onPageSizeChange={(perPage) => setFilters({ ...filters, perPage, page: 1 })}
      />
    </section>
  );
}
