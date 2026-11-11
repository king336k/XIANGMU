import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
// SPDX-License-Identifier: AGPL-3.0-only

export type ScheduledRecord = {
  id: string;
  name: string;
  start: string | null;
  target: string | null;
  status: string;
  path: string;
};
const format = (value: number) => new Date(value).toISOString().slice(0, 10).replaceAll("-", "/");
export function ScheduleTimeline({ rows, projectUrl }: { rows: ScheduledRecord[]; projectUrl: string }) {
  const dates = rows
    .flatMap((row) => [row.start, row.target].filter((date): date is string => !!date))
    .map((date) => Date.parse(date));
  if (!rows.length) return <p className="text-12 text-secondary">暂无已安排的任务或版本日期。</p>;
  const min = dates.length ? Math.min(...dates) : 0;
  const max = dates.length ? Math.max(...dates) : 0;
  const span = Math.max(86400000, max - min);
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
          const leftDate = row.start || row.target;
          const rightDate = row.target || row.start;
          const invalid = row.start && row.target && row.start > row.target;
          return (
            <Link
              key={row.id}
              to={`${projectUrl}/${row.path}`}
              className="grid grid-cols-[12rem_1fr] items-center gap-2 border-b border-subtle px-3 py-3 hover:bg-layer-1"
            >
              <span className="min-w-0 pr-2 text-12">
                <span className="line-clamp-2">{row.name}</span>
                <span className="mt-1 block text-10 text-secondary">
                  {row.start?.replaceAll("-", "/") || "待安排"} → {row.target?.replaceAll("-", "/") || "待安排"}
                </span>
              </span>
              <span className="relative h-8">
                {leftDate && rightDate && !invalid ? (
                  <span
                    className={`absolute top-2 h-4 min-w-1 rounded-sm ${["completed", "released"].includes(row.status) ? "bg-success-primary/70" : "bg-accent-primary/70"}`}
                    style={{
                      left: `${((Date.parse(leftDate) - min) / span) * 100}%`,
                      width: `${row.start && row.target ? Math.max(1, ((Date.parse(rightDate) - Date.parse(leftDate)) / span) * 100) : 1}%`,
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
