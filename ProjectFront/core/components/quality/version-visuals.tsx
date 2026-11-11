import { useState } from "react";
// SPDX-License-Identifier: AGPL-3.0-only
import { ArrowRight, Check, Flag } from "lucide-react";
import { flowLayers } from "./flow-graph";
import { versionStatuses, flowStatuses, nodeKinds } from "./version-types";
import type { FlowNode, VersionDetail, VersionSummary } from "./version-types";
const stateColors: Record<string, string> = {
  waiting: "#94a3b8",
  ready: "#4b86c6",
  completed: "#379b76",
  blocked: "#c94c5c",
};
export function VersionPhases({ status }: { status: string }) {
  const phases = ["planning", "development", "testing", "ready", "released"];
  const index = phases.indexOf(status);
  return (
    <ol aria-label="版本阶段" className="flex flex-wrap items-center gap-2 rounded-md border border-subtle p-3">
      {phases.map((key, i) => (
        <li key={key} className="flex items-center gap-2 text-12">
          <span
            className={`flex items-center gap-1.5 rounded px-2 py-1.5 ${i === index ? "bg-accent-subtle text-accent-primary" : i < index ? "text-success-primary" : "text-tertiary"}`}
          >
            {i < index ? (
              <Check className="size-3" />
            ) : (
              <span className="grid size-4 place-items-center rounded-full border border-current text-10">{i + 1}</span>
            )}
            {versionStatuses[key]}
          </span>
          {i < phases.length - 1 && <ArrowRight className="size-3 text-tertiary" />}
        </li>
      ))}
    </ol>
  );
}
export function VersionTimeline({ rows, onSelect }: { rows: VersionSummary[]; onSelect?: (id: string) => void }) {
  const dates = rows.flatMap((row) => [row.start_date, row.target_date].filter((x): x is string => !!x));
  const min = dates.length ? Math.min(...dates.map((x) => Date.parse(x))) : Date.now();
  const max = dates.length ? Math.max(...dates.map((x) => Date.parse(x))) : min + 86400000;
  const span = Math.max(86400000, max - min);
  return (
    <section aria-label="版本时间轴" className="overflow-x-auto rounded-md border border-subtle">
      <div className="min-w-[760px]">
        <div className="grid grid-cols-[16rem_1fr] border-b border-subtle bg-layer-1 p-3 text-12 text-secondary">
          <span>版本 / 负责人</span>
          <span className="flex justify-between">
            <span>{new Date(min).toISOString().slice(0, 10).replaceAll("-", "/")}</span>
            <span>{new Date(max).toISOString().slice(0, 10).replaceAll("-", "/")}</span>
          </span>
        </div>
        {rows.map((row) => (
          <button
            key={row.id}
            type="button"
            disabled={!onSelect}
            onClick={() => onSelect?.(row.id)}
            className="grid w-full grid-cols-[16rem_1fr] items-center border-b border-subtle p-3 text-left hover:bg-layer-1"
          >
            <span className="pr-4 text-13">
              <strong>{row.version}</strong> · {row.name}
              <span className="mt-1 block text-11 text-secondary">
                {row.owner_name || "未指定负责人"} · {versionStatuses[row.status]}
              </span>
            </span>
            <span className="relative h-12">
              {row.start_date && row.target_date ? (
                <span
                  className="absolute top-2 flex h-8 min-w-12 items-center justify-center overflow-hidden rounded px-2 text-11 text-white"
                  style={{
                    left: `${((Date.parse(row.start_date) - min) / span) * 100}%`,
                    width: `${Math.max(3, ((Date.parse(row.target_date) - Date.parse(row.start_date)) / span) * 100)}%`,
                    backgroundColor:
                      row.status === "released" ? "#379b76" : row.status === "testing" ? "#b28a36" : "#4b86c6",
                  }}
                >
                  {row.start_date.replaceAll("-", "/")} → {row.target_date.replaceAll("-", "/")}
                </span>
              ) : (
                <span className="text-12 text-tertiary">待安排日期</span>
              )}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
export function VersionFlow({
  version,
  onSelect,
  onEdit,
}: {
  version: VersionDetail;
  onSelect: (node: FlowNode) => void;
  onEdit?: (node: FlowNode) => void;
}) {
  const [fit, setFit] = useState(true);
  let layers: FlowNode[][];
  try {
    layers = flowLayers(version.flow_nodes);
  } catch (error) {
    return (
      <p role="alert" className="text-danger-primary">
        {error instanceof Error ? error.message : "流程不可用"}
      </p>
    );
  }
  if (!layers.length)
    return (
      <p className="rounded-md border border-dashed border-subtle p-6 text-center text-13 text-secondary">
        暂无流程节点。点击“编辑流程与分工”添加。
      </p>
    );
  const width = Math.max(700, layers.length * 258);
  const height = Math.max(240, Math.max(...layers.map((x) => x.length)) * 140);
  const positions = new Map(
    layers.flatMap((layer, col) =>
      layer.map((node, index) => [node.id, { x: col * 258 + 12, y: index * 140 + 18 }] as const)
    )
  );
  return (
    <section aria-label="并行分支流程图" className="rounded-md border border-subtle bg-surface-1 p-3">
      <div className="mb-3 flex justify-end">
        <button
          type="button"
          onClick={() => setFit(!fit)}
          className="rounded border border-subtle px-2 py-1 text-11 text-secondary"
        >
          {fit ? "原始尺寸" : "适应宽度"}
        </button>
      </div>
      <div className="overflow-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={fit ? "100%" : width}
          height={fit ? "auto" : height}
          role="img"
          aria-label="任务分叉与汇合，点击节点查看记录"
        >
          <defs>
            <marker id={`arrow-${version.id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8" fill="#94a3b8" />
            </marker>
          </defs>
          {version.flow_nodes.flatMap((node) =>
            node.depends_on.map((dep) => {
              const from = positions.get(dep)!;
              const to = positions.get(node.id)!;
              return (
                <path
                  key={`${dep}-${node.id}`}
                  d={`M${from.x + 212},${from.y + 48} H${from.x + 234} V${to.y + 48} H${to.x - 4}`}
                  fill="none"
                  stroke="#94a3b8"
                  strokeWidth="1.5"
                  markerEnd={`url(#arrow-${version.id})`}
                />
              );
            })
          )}
          {version.flow_nodes.map((node) => {
            const position = positions.get(node.id)!;
            const state = version.flow_state[node.id];
            return (
              <foreignObject key={node.id} x={position.x} y={position.y} width="212" height="112">
                <div className="relative h-28">
                  <button
                    type="button"
                    onClick={() => onSelect(node)}
                    aria-label={`${node.name}：${flowStatuses[state?.status] || "等待前置"}`}
                    className="flex h-28 w-full flex-col justify-between rounded-md border border-subtle bg-surface-1 p-3 text-left hover:border-strong"
                  >
                    <span className="flex w-full items-center gap-1.5 text-11 text-secondary">
                      <span
                        className="size-2 shrink-0 rounded-full"
                        style={{ backgroundColor: stateColors[state?.status] || stateColors.waiting }}
                      />
                      {flowStatuses[state?.status] || "等待前置"}
                      <span className="ml-auto">{nodeKinds[node.kind]}</span>
                    </span>
                    <strong className="line-clamp-2 text-13 font-medium text-primary">{node.name}</strong>
                    <span className="text-10 text-tertiary">
                      {node.depends_on.length > 1
                        ? node.join === "any"
                          ? "任一前置完成后开始"
                          : "全部前置完成后开始"
                        : node.depends_on.length
                          ? "等待前置完成"
                          : "起始节点"}
                      {node.target_date ? ` · ${node.target_date.replaceAll("-", "/")}` : ""}
                    </span>
                  </button>
                  {onEdit && (
                    <button
                      type="button"
                      aria-label={`编辑节点：${node.name}`}
                      onClick={() => onEdit(node)}
                      className="absolute right-2 bottom-2 rounded border border-subtle bg-surface-1 px-2 py-0.5 text-10 text-accent-primary hover:bg-layer-1"
                    >
                      编辑
                    </button>
                  )}
                </div>
              </foreignObject>
            );
          })}
        </svg>
      </div>
    </section>
  );
}
export function VersionMilestones({
  version,
  onSelect,
}: {
  version: VersionDetail;
  onSelect: (node: FlowNode) => void;
}) {
  const nodes = version.flow_nodes.filter((node) => node.kind === "milestone");
  return (
    <section aria-label="版本里程碑" className="space-y-3">
      {nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          onClick={() => onSelect(node)}
          className="flex w-full items-center gap-3 rounded-md border border-subtle p-4 text-left hover:bg-layer-1"
        >
          <Flag className="size-5 shrink-0" style={{ color: stateColors[version.flow_state[node.id]?.status] }} />
          <span className="flex-1">
            <strong className="text-13 font-medium">{node.name}</strong>
            <span className="mt-1 block text-11 text-secondary">
              {node.target_date?.replaceAll("-", "/") || "未设目标日期"} · {node.depends_on.length} 个前置节点
            </span>
          </span>
          <span className="text-12 text-secondary">
            {flowStatuses[version.flow_state[node.id]?.status] || "待安排"}
          </span>
        </button>
      ))}
      {!nodes.length && (
        <p className="rounded-md border border-dashed border-subtle p-6 text-13 text-secondary">尚未设置里程碑。</p>
      )}
    </section>
  );
}
