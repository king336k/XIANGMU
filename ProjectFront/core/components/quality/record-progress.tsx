import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";

import { CustomMenu } from "@plane/ui";
import { ChevronDown, Flag, GitBranch, CalendarRange, List } from "lucide-react";
import { renderNumericDateTime } from "@plane/utils";
import { ScheduleTimeline } from "./schedule-timeline";
import { qualityApi, errorMessage } from "./api";
import { Paging } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
type Event = { id: string; label: string; actor: string; date: string; note?: string };
type Data = {
  schedule: { id: string; name: string; start: string | null; target: string | null; status: string; path: string }[];
  stages: { key: string; name: string }[];
  current: string;
  events: Event[];
  event_pagination: { count: number; page: number; per_page: number };
  dates: { label: string; date: string | null }[];
  versions: {
    id: string;
    name: string;
    version: string;
    milestones: { id: string; name: string; date: string | null; status: string }[];
  }[];
};
export function RecordProgress({
  base,
  kind,
  id,
  projectUrl,
}: {
  base: string;
  kind: "plan" | "defect" | "requirement";
  id: string;
  projectUrl: string;
}) {
  const [mode, setMode] = useState("details");
  const pagination = useCollectionPagination(`${base}:history:${kind}:${id}`);
  const query = new URLSearchParams(pagination.query);
  query.set("kind", kind);
  query.set("id", id);
  const { data, error } = useSWR(mode !== "details" ? `${base}record-progress/?${query}` : null, (url: string) =>
    qualityApi.read<Data>(url)
  );
  const modes = [
    { key: "details", title: "详情", icon: List },
    { key: "stages", title: "阶段图", icon: GitBranch },
    { key: "schedule", title: "时间轴", icon: CalendarRange },
    { key: "timeline", title: "处理历程", icon: CalendarRange },
    { key: "milestones", title: "关联里程碑", icon: Flag },
  ];
  return (
    <section className="space-y-3">
      <div className="flex justify-end">
        <CustomMenu
          placement="bottom-end"
          closeOnSelect
          customButton={
            <span className="flex shrink-0 items-center gap-2 rounded-md border border-subtle px-3 py-1.5 text-12 whitespace-nowrap text-secondary">
              进度与历程
              <ChevronDown className="size-3" />
            </span>
          }
        >
          {modes.map((item) => (
            <CustomMenu.MenuItem key={item.key} onClick={() => setMode(item.key)}>
              <item.icon className="size-3.5" />
              {item.title}
              {mode === item.key ? " ✓" : ""}
            </CustomMenu.MenuItem>
          ))}
        </CustomMenu>
      </div>
      {mode !== "details" && (
        <div className="rounded-md border border-subtle bg-layer-1/40 p-4">
          {error && (
            <p role="alert" className="text-12 text-danger-primary">
              {errorMessage(error)}
            </p>
          )}
          {!data && !error && (
            <p role="status" className="text-12 text-secondary">
              正在读取…
            </p>
          )}
          {data && mode === "stages" && (
            <ol aria-label="业务阶段图" className="flex flex-wrap gap-2">
              {data.stages.map((stage, index) => (
                <li key={stage.key} className="flex items-center gap-2 text-12">
                  <span
                    className={`rounded-md border px-3 py-2 ${stage.key === data.current ? "border-accent-subtle-1 bg-accent-subtle font-medium text-accent-primary" : "border-subtle text-secondary"}`}
                  >
                    {stage.name}
                    {stage.key === data.current ? " · 当前" : ""}
                  </span>
                  {index < data.stages.length - 1 && <span className="text-tertiary">→</span>}
                </li>
              ))}
            </ol>
          )}
          {data && mode === "schedule" && <ScheduleTimeline rows={data.schedule} projectUrl={projectUrl} />}
          {data && mode === "timeline" && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3 text-11 text-secondary">
                {data.dates
                  .filter((item) => item.date)
                  .map((item) => (
                    <span key={item.label}>
                      {item.label}：
                      {/^\d{4}-\d{2}-\d{2}$/.test(item.date!)
                        ? item.date!.replaceAll("-", "/")
                        : renderNumericDateTime(item.date!)}
                    </span>
                  ))}
              </div>
              <ol aria-label="处理历程" className="space-y-4">
                {data.events.map((item) => (
                  <li key={item.id} className="relative border-l-2 border-subtle pl-4">
                    <span className="absolute top-1 -left-1.5 size-2.5 rounded-full bg-accent-primary" />
                    <p className="text-13 font-medium">{item.label}</p>
                    <p className="mt-1 text-11 text-secondary">
                      {item.actor} · {renderNumericDateTime(item.date)}
                    </p>
                    {item.note && <p className="mt-2 text-12 whitespace-pre-wrap text-secondary">{item.note}</p>}
                  </li>
                ))}
              </ol>
              {!data.event_pagination.count && <p className="text-12 text-secondary">暂无处理记录。</p>}
              <Paging {...pagination.paging} count={data.event_pagination.count} />
            </div>
          )}
          {data && mode === "milestones" && (
            <div className="space-y-3">
              {data.versions.map((version) => (
                <section key={version.id} className="space-y-2">
                  <Link
                    className="text-13 font-medium text-accent-primary"
                    to={`${projectUrl}/versions?version=${version.id}&display=milestones`}
                  >
                    {version.version} · {version.name} →
                  </Link>
                  {version.milestones.map((item) => (
                    <div
                      key={item.id}
                      className="flex flex-wrap justify-between gap-2 rounded border border-subtle px-3 py-2 text-12"
                    >
                      <span>{item.name}</span>
                      <span className="text-secondary">
                        {item.date?.replaceAll("-", "/") || "未安排日期"} ·{" "}
                        {item.status === "completed" ? "已完成" : item.status === "ready" ? "待确认" : "等待前置"}
                      </span>
                    </div>
                  ))}
                </section>
              ))}
              {!data.versions.length && <p className="text-12 text-secondary">尚未关联版本里程碑。</p>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
