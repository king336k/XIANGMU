import { TerminalPanel } from "./terminal-panel";
import { FilePanel } from "./file-panel";
// SPDX-License-Identifier: AGPL-3.0-only
import { lazy, Suspense, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { ChevronLeft, ChevronRight, Monitor, RefreshCw, Search } from "lucide-react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";

import { remoteDiagnosticsBase } from "./types";
import type { RemoteDevice, RobotTarget } from "./types";

const panelLoading = (
  <div role="status" className="p-5 text-13 text-secondary">
    正在加载…
  </div>
);
const AgentPanel = lazy(() => import("./agent-panel").then((module) => ({ default: module.AgentPanel })));

export function RemoteDiagnostics() {
  const { workspaceSlug } = useParams();
  const [params, setParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState("");
  const [terminalId, setTerminalId] = useState("");
  const [showDevices, setShowDevices] = useState(true);
  const projectId = params.get("project") || "";
  const query = new URLSearchParams({ workspace: workspaceSlug || "" });
  if (projectId) query.set("project", projectId);
  const perPage = [6, 12, 24].includes(Number(params.get("per_page"))) ? Number(params.get("per_page")) : 6;
  const requestedPage = Math.max(1, Number(params.get("page")) || 1);
  const search = params.get("search") || "";
  const state = params.get("status") || "all";
  query.set("page", String(requestedPage));
  query.set("per_page", String(perPage));
  if (search) query.set("search", search);
  if (state !== "all") query.set("status", state);
  if (selectedId || terminalId) query.set("active", [...new Set([selectedId, terminalId].filter(Boolean))].join(","));
  const update = (values: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { preventScrollReset: true });
  };
  const { data, error, mutate, isValidating } = useSWR(
    workspaceSlug ? `${remoteDiagnosticsBase}?${query}` : null,
    (url: string) =>
      qualityApi.read<{
        results: RemoteDevice[];
        active_results?: RemoteDevice[];
        count?: number;
        page?: number;
        can_manage: boolean;
      }>(url),
    { refreshInterval: 10000, keepPreviousData: true, refreshWhenHidden: false }
  );
  const activeDevices = [...(data?.active_results || []), ...(data?.results || [])];
  const count = data?.count ?? data?.results.length ?? 0;
  const page = data?.page ?? requestedPage;
  const totalPages = Math.max(1, Math.ceil(count / perPage));
  const selected = activeDevices.find((device) => device.id === selectedId);
  const terminalDevice = activeDevices.find((device) => device.id === terminalId && device.can_connect);
  const terminalRobot = terminalDevice?.capabilities.robot as RobotTarget | undefined;

  return (
    <div className="flex h-full min-h-0 flex-col px-4 py-5 sm:px-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="platform-page-title">远程诊断</h1>
          <p className="mt-2 text-13 text-secondary">选择采集电脑，查看终端、文件和处理进度。</p>
        </div>
        <button
          type="button"
          disabled={isValidating}
          onClick={() => void mutate()}
          className="flex items-center gap-2 rounded border border-subtle px-3 py-2 text-13 disabled:opacity-50"
        >
          <RefreshCw className="size-4" aria-hidden="true" />
          刷新设备
        </button>
      </div>
      {error && data && (
        <p role="alert" className="mb-4 text-12 text-warning-primary">
          设备状态刷新失败，稍后重试
        </p>
      )}
      {error && !data ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在读取现场电脑…
        </p>
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <section
            aria-label="采集电脑列表"
            className="flex min-h-0 flex-col rounded-lg border border-subtle bg-surface-1"
          >
            <div className="space-y-3 border-b border-subtle p-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-13 font-medium">
                  采集电脑 <span className="font-normal ml-1 text-12 text-secondary">{count}</span>
                </h2>
                <select
                  aria-label="设备在线状态"
                  value={state}
                  onChange={(event) => update({ status: event.target.value, page: "1" })}
                  className="rounded border border-subtle bg-surface-1 px-2 py-1 text-12"
                >
                  <option value="all">全部状态</option>
                  <option value="online">在线</option>
                  <option value="offline">离线</option>
                </select>
              </div>
              <form
                className="flex items-center gap-1 rounded-md border border-subtle px-2 focus-within:border-accent-strong"
                onSubmit={(event) => {
                  event.preventDefault();
                  update({ search: String(new FormData(event.currentTarget).get("search") || "").trim(), page: "1" });
                }}
              >
                <Search className="size-4 shrink-0 text-tertiary" aria-hidden="true" />
                <input
                  key={search}
                  name="search"
                  defaultValue={search}
                  aria-label="搜索采集电脑"
                  placeholder="用户名、IP 或主机名"
                  className="min-w-0 flex-1 bg-transparent py-2 text-13 outline-none"
                />
                <button type="submit" className="rounded px-2 py-1 text-12 text-secondary hover:bg-layer-1">
                  搜索
                </button>
              </form>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <button
                type="button"
                aria-expanded={showDevices}
                onClick={() => setShowDevices(!showDevices)}
                className="w-full px-3 py-2 text-left text-12 text-secondary lg:hidden"
              >
                {showDevices ? "收起设备列表" : "展开设备列表"}
              </button>
              <div
                aria-label="现场电脑"
                className={`${showDevices ? "grid" : "hidden"} max-h-72 grid-cols-1 gap-2 overflow-y-auto p-3 sm:grid-cols-2 lg:grid lg:max-h-none lg:grid-cols-1 lg:overflow-visible`}
              >
                {data.results.map((device) => (
                  <button
                    key={device.id}
                    type="button"
                    aria-pressed={selectedId === device.id}
                    onClick={() => {
                      setSelectedId(device.id);
                      if (terminalId !== device.id) setTerminalId("");
                    }}
                    className={`min-w-0 rounded-md border p-3 text-left transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong ${selectedId === device.id ? "border-accent-strong bg-surface-2" : "border-subtle"}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Monitor className="size-4 shrink-0 text-secondary" aria-hidden="true" />
                        <h2 className="truncate text-14 font-medium">
                          {device.username || "未知用户"}@{device.ip_address || "IP待确认"}
                        </h2>
                      </div>
                      <span className={`shrink-0 text-12 ${device.online ? "text-success-primary" : "text-secondary"}`}>
                        {device.online ? "在线" : "离线"}
                      </span>
                    </div>
                    <p className="font-mono mt-2 truncate text-12 text-secondary" title={device.hostname}>
                      {device.hostname || "未知主机"}
                    </p>
                    {device.name && device.name !== device.hostname && device.name !== device.username && (
                      <p className="mt-1 truncate text-12 text-tertiary" title={device.name}>
                        {device.name}
                      </p>
                    )}
                    {!device.can_connect && <p className="mt-2 text-12 text-secondary">无连接权限</p>}
                  </button>
                ))}

                {!data.results.length && (
                  <p role="status" className="col-span-full px-1 py-5 text-center text-13 text-secondary">
                    {search || state !== "all" ? "没有匹配的电脑" : "暂无可访问的电脑"}
                  </p>
                )}
              </div>
            </div>
            <nav
              aria-label="设备分页"
              className="flex flex-wrap items-center justify-between gap-2 border-t border-subtle p-3 text-12 text-secondary"
            >
              <select
                aria-label="每页电脑数量"
                value={perPage}
                onChange={(event) => update({ per_page: event.target.value, page: "1" })}
                className="rounded border border-subtle bg-surface-1 px-2 py-1"
              >
                {[6, 12, 24].map((size) => (
                  <option key={size} value={size}>
                    {size} 台/页
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label="上一页设备"
                  disabled={page <= 1}
                  onClick={() => update({ page: String(page - 1) })}
                  className="grid size-7 place-items-center rounded border border-subtle hover:bg-layer-1 disabled:opacity-30"
                >
                  <ChevronLeft className="size-3.5" />
                </button>
                <span aria-live="polite">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  aria-label="下一页设备"
                  disabled={page >= totalPages}
                  onClick={() => update({ page: String(page + 1) })}
                  className="grid size-7 place-items-center rounded border border-subtle hover:bg-layer-1 disabled:opacity-30"
                >
                  <ChevronRight className="size-3.5" />
                </button>
              </div>
            </nav>
          </section>
          <section
            aria-label="当前电脑操作"
            className="min-h-0 overflow-y-auto rounded-lg border border-subtle bg-surface-1"
          >
            {selected ? (
              <div className="space-y-4 p-4" key={selected.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="font-mono min-w-0 truncate text-13 text-secondary">
                    {selected.username}@{selected.ip_address || "IP待确认"}
                    {!selected.online ? " · 离线，请等待重新上线" : ""}
                  </p>
                  {!terminalDevice && (
                    <button
                      type="button"
                      disabled={!selected.online || !selected.can_connect}
                      onClick={() => setTerminalId(selected.id)}
                      className="rounded border border-subtle px-4 py-2 text-13 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      打开终端
                    </button>
                  )}
                </div>
                {terminalDevice && (
                  <TerminalPanel
                    key={terminalDevice.id}
                    device={terminalDevice}
                    robot={terminalRobot}
                    onClose={() => setTerminalId("")}
                  />
                )}
                <FilePanel device={selected} />
                <Suspense fallback={panelLoading}>
                  <AgentPanel device={selected} />
                </Suspense>
              </div>
            ) : (
              <div className="flex h-full min-h-64 flex-col items-center justify-center gap-3 p-6 text-center">
                <span className="grid size-12 place-items-center rounded-lg bg-layer-1 text-secondary">
                  <Monitor className="size-6" />
                </span>
                <h2 className="text-14 font-medium">选择一台采集电脑</h2>
                <p className="text-13 text-secondary">终端、文件传输和现场处理将在这里显示。</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
