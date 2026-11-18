// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { Monitor, RefreshCw } from "lucide-react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { AgentPanel } from "./agent-panel";
import { TerminalPanel } from "./terminal-panel";
import { FilePanel } from "./file-panel";
import { remoteDiagnosticsBase } from "./types";
import type { RemoteDevice } from "./types";

export function RemoteDiagnostics() {
  const { workspaceSlug } = useParams();
  const [params] = useSearchParams();
  const projectId = params.get("project") || "";
  const query = new URLSearchParams({ workspace: workspaceSlug || "" });
  if (projectId) query.set("project", projectId);
  const { data, error, mutate, isValidating } = useSWR(
    workspaceSlug ? `${remoteDiagnosticsBase}?${query}` : null,
    (url: string) => qualityApi.read<{ results: RemoteDevice[]; can_manage: boolean }>(url),
    { refreshInterval: 10000 }
  );
  const [selectedId, setSelectedId] = useState("");
  const [terminalId, setTerminalId] = useState("");
  const selected = data?.results.find((device) => device.id === selectedId);
  const terminalDevice = !error && data?.results.find((device) => device.id === terminalId && device.can_connect);

  return (
    <div className="h-full overflow-y-auto px-4 py-6 sm:px-6 xl:px-8">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="platform-page-title">远程诊断</h1>
          <p className="mt-2 text-13 text-secondary">选择现场电脑，打开终端或关联反馈排查问题。</p>
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
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在读取现场电脑…
        </p>
      ) : !data.results.length ? (
        <div role="status" className="rounded border border-subtle p-6 text-13 text-secondary">
          暂无可访问的电脑。请先在现场电脑完成接入，并确认项目授权。
        </div>
      ) : (
        <div className="space-y-5">
          <div aria-label="现场电脑" className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {data.results.map((device) => (
              <button
                key={device.id}
                type="button"
                aria-pressed={selectedId === device.id}
                onClick={() => {
                  setSelectedId(device.id);
                  if (terminalId !== device.id) setTerminalId("");
                }}
                className={`min-w-0 rounded border p-4 text-left transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-strong ${selectedId === device.id ? "border-accent-strong bg-surface-2" : "border-subtle"}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <Monitor className="size-4 shrink-0 text-secondary" aria-hidden="true" />
                    <h2 className="truncate text-14 font-medium">{device.username || "未知用户"}</h2>
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
          </div>
          {selected && (
            <div className="space-y-4 border-t border-subtle pt-5" key={selected.id}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="font-mono min-w-0 truncate text-13 text-secondary">
                  {selected.username}@{selected.hostname}
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
                <TerminalPanel key={terminalDevice.id} device={terminalDevice} onClose={() => setTerminalId("")} />
              )}
              <FilePanel device={selected} />
              <AgentPanel device={selected} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
