import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { ConfigurationChangeDiff } from "./configuration-change-diff";
import { sortBy } from "lodash-es";
import useSWR from "swr";
import { CustomMenu } from "@plane/ui";
import { ChevronDown, Flag, GitBranch, CalendarRange, List } from "lucide-react";
import { renderNumericDateTime } from "@plane/utils";
import { ScheduleTimeline } from "./schedule-timeline";
import { DefectFlowGuidance } from "./defect-flow-guidance";
import type { Context, Defect, RemoteProcess } from "./types";
import { qualityApi, errorMessage } from "./api";
import { Badge, Modal, Paging } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
type Event = {
  id: string;
  label: string;
  actor: string;
  date: string;
  note?: string;
  tone?: string;
  details?: string;
  remote_process?: RemoteProcess | null;
};
const technicalId = /\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/i;
function eventSummary(event: Event, currentCode?: string) {
  const summary = event.remote_process?.summary || event.note || "";
  if (technicalId.test(summary) || (!event.remote_process && (summary.length > 180 || summary.split("\n").length > 3)))
    return "原始说明见详情";
  const code = [event.remote_process?.defect_code, currentCode].find(
    (value) => value && summary.startsWith(value) && (!summary[value.length] || /[\s·：:]/.test(summary[value.length]))
  );
  return code ? summary.slice(code.length).replace(/^[\s·：:]+/, "") || summary : summary;
}

type Data = {
  schedule: { id: string; name: string; start: string | null; target: string | null; status: string; path: string }[];
  stages: { key: string; name: string; state?: "current" | "completed" | "pending" | "skipped" }[];
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
const modes = [
  { key: "stages", title: "阶段图", icon: GitBranch },
  { key: "schedule", title: "时间轴", icon: CalendarRange },
  { key: "timeline", title: "处理历程", icon: List },
  { key: "milestones", title: "关联里程碑", icon: Flag },
];
const dateLabel = (value: string) =>
  /^\d{4}-\d{2}-\d{2}$/.test(value) ? value.replaceAll("-", "/") : renderNumericDateTime(value);
export function RecordProgress({
  base,
  kind,
  id,
  projectUrl,
  defectFlow,
}: {
  base: string;
  kind: "plan" | "defect" | "requirement";
  id: string;
  projectUrl: string;
  defectFlow?: {
    value: Defect;
    context: Context;
    activeTab: string;
    onNavigate: (tab: string) => void;
    expanded: boolean;
    onExpandedChange: (expanded: boolean) => void;
  };
}) {
  const [mode, setMode] = useState("details");
  const inlineStages = defectFlow?.expanded ?? false;
  const selectMode = (nextMode: string) => {
    if (nextMode === "stages" && kind === "defect" && defectFlow) {
      defectFlow.onExpandedChange(!inlineStages);
      return;
    }
    setMode(nextMode);
  };
  const pagination = useCollectionPagination(`${base}:history:${kind}:${id}`);
  const query = new URLSearchParams(pagination.query);
  query.set("kind", kind);
  query.set("id", id);
  const { data, error, mutate } = useSWR(
    mode !== "details" ? `${base}record-progress/?${query}` : null,
    (url: string) => qualityApi.read<Data>(url)
  );
  const days = new Map<string, Event[]>();
  for (const event of sortBy(data?.events || [], (row) => Date.parse(row.date))) {
    const day = dateLabel(event.date).slice(0, 10);
    days.set(day, [...(days.get(day) || []), event]);
  }
  const latestDay = [...days.keys()].at(-1);
  const versionLink = (versionId: string) =>
    `${projectUrl.replace(/\/$/, "")}/versions/?${new URLSearchParams({ version: versionId, display: "milestones" })}`;
  return (
    <section>
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
            <CustomMenu.MenuItem key={item.key} onClick={() => selectMode(item.key)}>
              <item.icon className="size-3.5" />
              {item.title}
            </CustomMenu.MenuItem>
          ))}
        </CustomMenu>
      </div>
      {inlineStages && kind === "defect" && defectFlow && (
        <div className="mt-2 rounded-md border border-subtle bg-layer-1 p-3">
          <DefectFlowGuidance
            base={base}
            value={defectFlow.value}
            context={defectFlow.context}
            activeTab={defectFlow.activeTab}
            onNavigate={(tab) => {
              selectMode("details");
              defectFlow.onNavigate(tab);
            }}
          />
        </div>
      )}
      {mode !== "details" && !(kind === "defect" && defectFlow && mode === "stages") && (
        <Modal title="进度与历程" width="wide" onClose={() => setMode("details")}>
          <nav aria-label="进度展示方式" className="platform-selection-group">
            {modes.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-current={mode === item.key ? "page" : undefined}
                onClick={() => selectMode(item.key)}
                className="flex items-center gap-2 text-13"
              >
                <item.icon className="size-3.5" />
                {item.title}
              </button>
            ))}
          </nav>
          {error && (
            <p role="alert" className="text-12 text-danger-primary">
              {errorMessage(error)}{" "}
              <button type="button" onClick={() => void mutate()} className="underline">
                重试
              </button>
            </p>
          )}
          {!data && !error && (
            <p role="status" className="text-12 text-secondary">
              正在读取…
            </p>
          )}
          {data && mode === "stages" && kind !== "defect" && (
            <ol aria-label="业务阶段图" className="m-0 flex list-none flex-wrap gap-3 p-0">
              {data.stages.map((stage, index) => {
                const state = stage.key === data.current ? "current" : stage.state || "pending";
                return (
                  <li
                    key={stage.key}
                    data-stage={stage.key}
                    data-state={state}
                    title={state === "skipped" ? "业务状态未单独记录该阶段" : undefined}
                    className="flex items-center gap-3"
                  >
                    <div
                      className={`space-y-2 rounded-md border px-4 py-3 ${state === "current" ? "border-accent-subtle bg-accent-subtle" : state === "completed" ? "border-success-subtle bg-success-subtle" : "border-subtle bg-surface-1"}`}
                    >
                      <p className="text-13 font-medium">{stage.name}</p>
                      <Badge
                        value={state === "current" ? "running" : state === "completed" ? "passed" : "neutral"}
                        label={
                          state === "current"
                            ? "当前阶段"
                            : state === "completed"
                              ? "已完成"
                              : state === "skipped"
                                ? "未单独记录"
                                : "未开始"
                        }
                        variant="plain"
                      />
                    </div>
                    {index < data.stages.length - 1 && (
                      <span aria-hidden="true" className="text-tertiary">
                        →
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
          {data && mode === "schedule" && <ScheduleTimeline rows={data.schedule} projectUrl={projectUrl} />}
          {data && mode === "timeline" && (
            <div className="space-y-4">
              {!!data.dates.some((item) => item.date) && (
                <div className="flex flex-wrap gap-3 text-11 text-secondary">
                  {data.dates
                    .filter((item) => item.date)
                    .map((item) => (
                      <span key={item.label}>
                        {item.label}：{dateLabel(item.date!)}
                      </span>
                    ))}
                </div>
              )}
              {[...days].map(([day, events]) => (
                <details key={day} open={day === latestDay} className="rounded-md border border-subtle">
                  <summary className="cursor-pointer px-3 py-2 text-12 text-secondary">
                    {day} · {events.length} 条记录
                  </summary>
                  <ul aria-label="处理历程" className="m-0 list-none space-y-3 px-3 pb-3">
                    {events.map((item) => (
                      <li key={item.id} className="border-l-2 border-subtle pl-3">
                        <div className="flex flex-wrap items-center gap-2 text-12">
                          <strong className="font-medium">{item.actor || "系统"}</strong>
                          <Badge value={item.tone || "neutral"} label={item.label} variant="plain" />
                          <time dateTime={item.date} className="text-11 text-secondary">
                            {renderNumericDateTime(item.date)}
                          </time>
                        </div>
                        {eventSummary(item, defectFlow?.value.code) && (
                          <p className="mt-1 text-12 break-words whitespace-pre-wrap text-secondary">
                            {eventSummary(item, defectFlow?.value.code)}
                          </p>
                        )}
                        {(item.remote_process ||
                          item.details ||
                          (item.note &&
                            (technicalId.test(item.note) ||
                              item.note.length > 180 ||
                              item.note.split("\n").length > 3))) && (
                          <details className="mt-2 text-12 text-secondary">
                            <summary className="cursor-pointer">查看操作详情</summary>
                            <dl className="mt-2 space-y-3">
                              {item.remote_process?.defect_code && (
                                <div>
                                  <dt className="text-tertiary">任务</dt>
                                  <dd>{eventSummary(item, defectFlow?.value.code).split(" · ")[0]}</dd>
                                </div>
                              )}
                              {item.remote_process?.target && (
                                <div>
                                  <dt className="text-tertiary">目标</dt>
                                  <dd>
                                    {item.remote_process.target.label || "现场"} ·{" "}
                                    {item.remote_process.target.username || "用户名待确认"}@
                                    {item.remote_process.target.host || "IP待确认"}
                                  </dd>
                                </div>
                              )}
                              {!!item.remote_process?.command?.argv?.length && (
                                <div>
                                  <dt className="text-tertiary">命令参数</dt>
                                  <dd>
                                    <pre className="max-h-48 overflow-auto break-words whitespace-pre-wrap">
                                      {JSON.stringify(item.remote_process.command.argv, null, 2)}
                                    </pre>
                                  </dd>
                                </div>
                              )}
                              {item.remote_process?.command?.path && !item.remote_process.command.changes?.length && (
                                <div>
                                  <dt className="text-tertiary">文件位置</dt>
                                  <dd className="break-all">{item.remote_process.command.path}</dd>
                                </div>
                              )}
                              {!!item.remote_process?.command?.changes?.length && (
                                <div>
                                  <dt className="text-tertiary">配置差异</dt>
                                  <dd className="mt-2">
                                    <ConfigurationChangeDiff command={item.remote_process.command} />
                                  </dd>
                                </div>
                              )}
                              {item.remote_process?.command?.exit_code !== undefined &&
                                item.remote_process.command.exit_code !== null && (
                                  <div>
                                    <dt className="text-tertiary">退出码</dt>
                                    <dd>{item.remote_process.command.exit_code}</dd>
                                  </div>
                                )}
                              {item.remote_process?.details && (
                                <div>
                                  <dt className="text-tertiary">执行说明</dt>
                                  <dd className="break-words whitespace-pre-wrap">{item.remote_process.details}</dd>
                                </div>
                              )}
                              {(item.remote_process?.command?.expected_sha256 ||
                                item.remote_process?.command?.sha256 ||
                                item.remote_process?.command?.backup) && (
                                <div className="text-11 break-all text-tertiary">
                                  {item.remote_process.command.backup && (
                                    <p>备份：{item.remote_process.command.backup}</p>
                                  )}
                                  {item.remote_process.command.expected_sha256 && (
                                    <p>
                                      {item.remote_process.command.kind === "patch_file"
                                        ? "修改前校验："
                                        : "预期校验值："}
                                      {item.remote_process.command.expected_sha256}
                                    </p>
                                  )}
                                  {item.remote_process.command.sha256 && (
                                    <p>
                                      {item.remote_process.command.kind === "patch_file"
                                        ? "修改后校验："
                                        : "文件校验值："}
                                      {item.remote_process.command.sha256}
                                    </p>
                                  )}
                                </div>
                              )}
                              <div>
                                <details>
                                  <summary className="cursor-pointer text-11 text-tertiary">技术记录</summary>
                                  <div className="mt-2 space-y-2 text-11 text-tertiary">
                                    <p>{item.remote_process?.defect_code}</p>{" "}
                                    <div>
                                      <dt className="text-tertiary">原始记录</dt>
                                      <dd className="break-words whitespace-pre-wrap">
                                        {Array.from(
                                          new Set(
                                            [item.details, item.note, item.remote_process?.summary].filter(Boolean)
                                          )
                                        ).join("\n")}
                                      </dd>
                                    </div>
                                    {(item.remote_process?.run_id || item.remote_process?.command_id) && (
                                      <div className="border-t border-subtle pt-2 text-11 break-all text-tertiary">
                                        {item.remote_process.run_id && <p>任务ID：{item.remote_process.run_id}</p>}
                                        {item.remote_process.command_id && (
                                          <p>命令ID：{item.remote_process.command_id}</p>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                </details>
                              </div>
                            </dl>
                          </details>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
              {!data.event_pagination.count && <p className="text-12 text-secondary">暂无处理记录。</p>}
              <Paging {...pagination.paging} count={data.event_pagination.count} />
            </div>
          )}
          {data && mode === "milestones" && (
            <div className="space-y-4">
              {data.versions.map((version) => (
                <section key={version.id} className="rounded-md border border-subtle p-4">
                  <Link className="text-13 font-medium text-accent-primary" to={versionLink(version.id)}>
                    {version.version} · {version.name} →
                  </Link>
                  <div className="mt-3 space-y-2">
                    {version.milestones.map((item) => (
                      <Link
                        key={item.id}
                        to={versionLink(version.id)}
                        className="flex flex-wrap items-center justify-between gap-2 rounded border border-subtle px-3 py-2 text-12 hover:bg-layer-1"
                      >
                        <span className="min-w-0 flex-1 break-words">{item.name}</span>
                        <span className="text-secondary">{item.date ? dateLabel(item.date) : "未安排日期"}</span>
                        <Badge
                          value={
                            item.status === "completed"
                              ? "passed"
                              : item.status === "ready"
                                ? "review"
                                : item.status === "blocked"
                                  ? "blocked"
                                  : "neutral"
                          }
                          label={
                            item.status === "completed"
                              ? "已完成"
                              : item.status === "ready"
                                ? "待确认"
                                : item.status === "blocked"
                                  ? "关联阻塞"
                                  : "等待前置"
                          }
                        />
                      </Link>
                    ))}
                  </div>
                  {!version.milestones.length && <p className="mt-3 text-12 text-secondary">本版本暂无里程碑。</p>}
                </section>
              ))}
              {!data.versions.length && <p className="text-12 text-secondary">尚未关联版本里程碑。</p>}
            </div>
          )}
        </Modal>
      )}
    </section>
  );
}
