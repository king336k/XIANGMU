// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { renderNumericDateTime } from "@plane/utils";
import { Button } from "@plane/ui";
import { RotateCw } from "lucide-react";
import { attachmentDisplayName, errorMessage, qualityApi } from "./api";

type ModuleInfo = {
  key: string;
  version: string;
  branch: string;
  commit: string;
  commitMessage: string;
  commitDate: string;
  builtAt: string;
  generatedAt: string;
  image: string;
};
type Component = ModuleInfo & {
  label: string;
  location: "host" | "robot" | "remote" | "web";
  status: "available" | "unavailable" | "excluded";
  source: string;
  reason: string;
  submodules: ModuleInfo[];
  omittedSubmodules: number;
  hostUsername?: string;
};
type SnapshotRow = {
  file: { id: string; name: string; sha256: string };
  snapshot: {
    eventId: string;
    capturedAt: string;
    components: Component[];
    comparison: {
      status: "match" | "mismatch" | "unknown";
      items: { label: string; local: string; remote: string; match: boolean }[];
    };
  };
};
type SnapshotResponse = { count: number; results: SnapshotRow[] };

const statusNames = { available: "可用", unavailable: "缺失", excluded: "未纳入" };
const locationNames = { host: "采集电脑", robot: "机器人", remote: "机器人端", web: "采集电脑" };
const componentName = (row: Component) => (row.key === "project" ? "合并 DAQ 主程序" : row.label);
function versionName(row: ModuleInfo) {
  const values = [...new Set([row.version, row.branch].filter((value) => value && value !== "HEAD"))];
  return values.join(" · ") || (row.commit ? "固定提交，未标注版本" : "版本未记录");
}
const shortCommit = (commit: string) => (commit ? commit.slice(0, 10) : "未记录");
const displayTime = (value: string) => (value ? renderNumericDateTime(value) : "未记录");

function ComponentRow({ component }: { component: Component }) {
  const details: [string, string][] = [
    ["完整提交", component.commit],
    ["提交说明", component.commitMessage],
    ["提交时间", component.commitDate],
    ["构建时间", component.builtAt],
    ["版本文件生成时间", component.generatedAt],
    ["镜像", component.image],
    ["来源位置", component.source],
    ["说明", component.reason],
  ];
  return (
    <details className="min-w-0 border-b border-subtle last:border-b-0">
      <summary className="grid cursor-pointer list-none grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2 text-12 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,.7fr)_auto]">
        <span className="min-w-0 font-medium break-words">{componentName(component)}</span>
        <span className="min-w-0 break-all text-secondary max-sm:col-start-1 max-sm:row-start-2">
          {versionName(component)}
        </span>
        <code className="min-w-0 text-11 break-all text-secondary max-sm:col-start-2 max-sm:row-start-2">
          {shortCommit(component.commit)}
        </code>
        <span className="text-11 whitespace-nowrap text-secondary">{statusNames[component.status]}</span>
      </summary>
      <div className="pb-3 pl-2 text-11 text-secondary">
        <p>
          {["host", "web"].includes(component.location)
            ? `采集电脑：${component.hostUsername || "用户名未记录"}`
            : `位置：${locationNames[component.location]}`}
        </p>
        <dl className="mt-2 grid min-w-0 gap-x-3 gap-y-1 sm:grid-cols-[max-content_minmax(0,1fr)]">
          {details
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <div key={label} className="min-w-0 sm:contents">
                <dt className="font-medium">{label}</dt>
                <dd className="min-w-0 break-all">{value}</dd>
              </div>
            ))}
        </dl>
        {component.submodules.length > 0 && (
          <div className="mt-2 space-y-1">
            <p className="font-medium">子模块</p>
            {component.submodules.map((item) => (
              <div key={item.key} className="min-w-0 break-all">
                {item.key} · {versionName(item)} · {item.commit || "提交未记录"}
                {item.commitMessage && <> · {item.commitMessage}</>}
                {item.commitDate && <> · {item.commitDate}</>}
                {item.builtAt && <> · 构建于 {item.builtAt}</>}
                {item.generatedAt && <> · 版本文件生成于 {item.generatedAt}</>}
                {item.image && <> · 镜像 {item.image}</>}
              </div>
            ))}
            {component.omittedSubmodules > 0 && <p>另有 {component.omittedSubmodules} 个子模块未写入快照</p>}
          </div>
        )}
      </div>
    </details>
  );
}

export function DeploymentSnapshots({
  base,
  defectId,
  compact = false,
  reportFileIds,
}: {
  base: string;
  defectId: string;
  compact?: boolean;
  reportFileIds?: string[];
}) {
  const { data, error, isLoading, mutate } = useSWR(`${base}defects/${defectId}/deployment-snapshots/`, (url: string) =>
    qualityApi.read<SnapshotResponse>(url)
  );
  const [selection, setSelection] = useState("");
  const visibleData = error ? undefined : data;
  const associated = compact ? visibleData?.results.find((row) => reportFileIds?.includes(row.file.id)) : undefined;
  const selected = compact
    ? associated || visibleData?.results[0]
    : visibleData?.results.find((row) => row.file.id === selection) || visibleData?.results[0];
  const components = selected?.snapshot.components || [];
  const available = components.filter((row) => row.status === "available").length;
  const unavailable = components.filter((row) => row.status === "unavailable").length;
  return (
    <section aria-label="现场版本" className="min-w-0">
      <details open className="platform-record-section">
        <summary className="cursor-pointer text-13 font-semibold text-primary">现场版本</summary>
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            {!compact && visibleData && visibleData.count > 1 && (
              <select
                aria-label="选择反馈版本快照"
                value={selected?.file.id || ""}
                onChange={(event) => setSelection(event.target.value)}
                className="max-w-full rounded border border-subtle bg-surface-1 px-2 py-1 text-11 text-primary"
              >
                {visibleData.results.map((row, index) => (
                  <option key={row.file.id} value={row.file.id}>
                    {index === 0 ? "最新 · " : ""}
                    {displayTime(row.snapshot.capturedAt)} · {row.snapshot.eventId.slice(0, 8)}
                  </option>
                ))}
              </select>
            )}
          </div>
          {isLoading && !error && (
            <p role="status" className="text-12 text-secondary">
              正在读取反馈版本…
            </p>
          )}
          {error && (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-12 text-danger-primary">
              <span>{errorMessage(error)}</span>
              <Button
                type="button"
                size="sm"
                variant="neutral-primary"
                onClick={() => void mutate()}
                aria-label="重试读取反馈版本"
              >
                <RotateCw className="size-3.5" />
              </Button>
            </div>
          )}
          {visibleData && visibleData.count === 0 && <p className="text-12 text-secondary">此反馈未记录版本快照。</p>}
          {selected && (
            <>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-11 text-secondary">
                <span>取证于 {displayTime(selected.snapshot.capturedAt)}</span>
                <span>
                  {available} 可用 · {unavailable} 缺失
                </span>
                {components.some((row) => row.status === "excluded") && (
                  <span>{components.filter((row) => row.status === "excluded").length} 未纳入</span>
                )}
              </div>
              {compact ? (
                <p className="min-w-0 text-12 leading-5 break-words text-secondary">
                  {associated ? "本报告材料中的版本快照：" : "最新上传版本，尚未与当前报告关联："}
                  {components
                    .filter((row) => row.status === "available")
                    .slice(0, 3)
                    .map(
                      (row) =>
                        `${componentName(row)} ${row.version && row.version !== "HEAD" ? row.version : shortCommit(row.commit)}`
                    )
                    .join(" · ") || "暂无可用组件版本"}
                  。版本差异需结合日志核实。
                </p>
              ) : (
                <>
                  <div className="min-w-0 border-t border-subtle">
                    <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,.7fr)_auto] gap-x-3 border-b border-subtle py-2 text-11 font-medium text-secondary sm:grid">
                      <span>组件</span>
                      <span>版本 / 分支</span>
                      <span>提交</span>
                      <span>状态</span>
                    </div>
                    {components.map((row) => (
                      <ComponentRow key={row.key} component={row} />
                    ))}
                  </div>
                  {selected.snapshot.comparison.items.length > 0 && (
                    <details className="text-11 text-secondary">
                      <summary className="cursor-pointer">
                        版本对照 ·{" "}
                        {selected.snapshot.comparison.status === "match"
                          ? "一致"
                          : selected.snapshot.comparison.status === "mismatch"
                            ? "存在差异"
                            : "未确认"}
                      </summary>
                      <ul className="mt-1 space-y-1">
                        {selected.snapshot.comparison.items.map((item) => (
                          <li key={`${item.label}:${item.local}:${item.remote}`} className="min-w-0 break-all">
                            {item.label}：{item.local || "未记录"} / {item.remote || "未记录"} ·{" "}
                            {item.match ? "一致" : "有差异"}
                          </li>
                        ))}
                      </ul>
                      <p className="mt-1">版本差异需结合日志核实。</p>
                    </details>
                  )}
                  <details className="text-11 text-secondary">
                    <summary className="cursor-pointer">快照来源与核对信息</summary>
                    <div className="mt-1 min-w-0 break-all">
                      版本来源文件：{attachmentDisplayName(selected.file.name)}
                      <br />
                      SHA256：{selected.file.sha256}
                      <br />
                      文件 ID：{selected.file.id}
                    </div>
                  </details>
                </>
              )}
            </>
          )}
        </div>
      </details>
    </section>
  );
}
