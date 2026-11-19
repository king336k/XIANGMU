import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
// SPDX-License-Identifier: AGPL-3.0-only
import { Badge } from "./shared";
export type ScheduledRecord = {
  id: string;
  name: string;
  start: string | null;
  target: string | null;
  status: string;
  path: string;
};
const parse = (value: string | null) => (value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null);
const format = (value: number) => new Date(value).toISOString().slice(0, 10).replaceAll("-", "/");
export function ScheduleTimeline({ rows, projectUrl }: { rows: ScheduledRecord[]; projectUrl: string }) {
  const dates = rows.flatMap((row) =>
    [parse(row.start), parse(row.target)].filter((date): date is number => date !== null)
  );
  if (!rows.length) return <p className="text-12 text-secondary">暂无已安排的任务或版本日期。</p>;
  const min = dates.length ? Math.min(...dates) : 0,
    max = dates.length ? Math.max(...dates) : 0,
    span = Math.max(86400000, max - min);
  return (
    <div aria-label="任务与版本时间轴" className="overflow-x-auto rounded-md border border-subtle bg-surface-1">
      <div className="min-w-[640px]">
        {dates.length > 0 && (
          <div className="grid grid-cols-[12rem_1fr] border-b border-subtle bg-layer-1 px-3 py-2 text-11 text-secondary">
            <span>任务 / 版本</span>
            <span className="flex justify-between">
              <span>{format(min)}</span>
              <span>{format(max)}</span>
            </span>
          </div>
        )}
        {rows.map((row) => {
          const start = parse(row.start),
            target = parse(row.target),
            left = start ?? target,
            right = target ?? start;
          const invalid =
            (!!row.start && start === null) ||
            (!!row.target && target === null) ||
            (start !== null && target !== null && start > target);
          const complete = ["completed", "released", "closed"].includes(row.status),
            cancelled = ["cancelled", "canceled", "backlog", "pending", "unstarted", "waiting", "planning"].includes(
              row.status
            );
          return (
            <Link
              key={row.id}
              to={`${projectUrl.replace(/\/$/, "")}/${row.path.replace(/^\//, "")}`}
              className="grid grid-cols-[12rem_1fr] items-center gap-2 border-b border-subtle px-3 py-3 hover:bg-layer-1"
            >
              <span className="min-w-0 pr-2 text-12">
                <span className="line-clamp-2">{row.name}</span>
                <span className="mt-1 block text-10 text-secondary">
                  {start !== null && target !== null
                    ? `${format(start)} → ${format(target)}`
                    : start !== null
                      ? `开始：${format(start)}`
                      : target !== null
                        ? `目标：${format(target)}`
                        : "未安排日期"}
                </span>
                <span className="mt-1 inline-flex">
                  <Badge
                    variant="plain"
                    value={
                      complete
                        ? "passed"
                        : cancelled
                          ? "neutral"
                          : row.status === "blocked"
                            ? "blocked"
                            : row.status === "ready"
                              ? "review"
                              : "running"
                    }
                    label={
                      (
                        {
                          open: "待处理",
                          pending_tech: "待技术确认",
                          needs_tech: "待技术处理",
                          completed: "已完成",
                          released: "已发布",
                          closed: "已关闭",
                          cancelled: "已取消",
                          canceled: "已取消",
                          backlog: "待安排",
                          pending: "未开始",
                          unstarted: "未开始",
                          waiting: "等待前置",
                          planning: "规划中",
                          started: "进行中",
                          in_progress: "处理中",
                          development: "开发中",
                          testing: "测试中",
                          ready: "待发布",
                          blocked: "阻塞",
                        } as Record<string, string>
                      )[row.status] || row.status
                    }
                  />
                </span>
              </span>
              <span className="relative h-8">
                {left !== null && right !== null && !invalid ? (
                  <span
                    data-date-kind={start !== null && target !== null ? "range" : "point"}
                    className={`absolute top-2 h-4 ${start === null || target === null ? "w-1 -translate-x-1/2 rounded-full" : "min-w-1 rounded-sm"} ${complete ? "bg-success-primary/70" : cancelled ? "border border-strong bg-layer-1" : row.status === "blocked" ? "bg-danger-primary/70" : row.status === "ready" ? "bg-warning-primary/70" : "bg-accent-primary/70"}`}
                    style={{
                      left: `${((left - min) / span) * 100}%`,
                      ...(start !== null && target !== null
                        ? { width: `${Math.max(1, ((right - left) / span) * 100)}%` }
                        : {}),
                    }}
                  />
                ) : (
                  <span className={`text-11 ${invalid ? "text-danger-primary" : "text-tertiary"}`}>
                    {invalid ? "日期待核对" : "未安排日期"}
                  </span>
                )}
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
