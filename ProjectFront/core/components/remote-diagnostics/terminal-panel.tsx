// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { remoteDiagnosticsBase } from "./types";
import type { RemoteDevice, TerminalStatus } from "./types";
import { TerminalConnection } from "./terminal-connection";

export function TerminalPanel({ device, onClose }: { device: RemoteDevice; onClose: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<TerminalStatus>("connecting");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let teardown: (() => void) | undefined;
    async function connect() {
      const [{ Terminal }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (cancelled || !containerRef.current) return;
      const terminal = new Terminal({
        cursorBlink: true,
        fontFamily: '"IBM Plex Mono", "Cascadia Code", "JetBrains Mono", Menlo, Consolas, monospace',
        fontSize: 14,
        lineHeight: 1.25,
        minimumContrastRatio: 4.5,
        scrollback: 5000,
        theme: {
          background: "#101318",
          foreground: "#e5e7eb",
          cursor: "#a7f3d0",
          selectionBackground: "#334155",
          black: "#1e293b",
          red: "#f87171",
          green: "#6ee7b7",
          yellow: "#fcd34d",
          blue: "#93c5fd",
          magenta: "#d8b4fe",
          cyan: "#67e8f9",
          white: "#e5e7eb",
          brightBlack: "#94a3b8",
          brightRed: "#fca5a5",
          brightGreen: "#a7f3d0",
          brightYellow: "#fde68a",
          brightBlue: "#bfdbfe",
          brightMagenta: "#e9d5ff",
          brightCyan: "#a5f3fc",
          brightWhite: "#f8fafc",
        },
        allowProposedApi: false,
      });
      const fit = new FitAddon();
      terminal.loadAddon(fit);
      terminal.open(containerRef.current);
      fit.fit();
      void document.fonts.ready.then(() => {
        if (!cancelled && containerRef.current?.clientWidth) fit.fit();
        return undefined;
      });
      const connection = new TerminalConnection(
        qualityApi,
        remoteDiagnosticsBase,
        (bytes) => terminal.write(bytes),
        (nextStatus, cause) => {
          if (cancelled) return;
          setStatus(nextStatus);
          terminal.options.disableStdin = nextStatus !== "open";
          if (cause) setError(errorMessage(cause));
          if (nextStatus === "open") terminal.focus();
        }
      );
      const input = terminal.onData((data) => connection.input(data));
      const resize = terminal.onResize(({ cols, rows }) => connection.resize(cols, rows));
      const observer = new ResizeObserver(() => {
        if (containerRef.current?.clientWidth) fit.fit();
      });
      observer.observe(containerRef.current);
      teardown = () => {
        observer.disconnect();
        input.dispose();
        resize.dispose();
        connection.dispose();
        terminal.dispose();
      };
      void connection.open(device.id, terminal.cols, terminal.rows);
    }
    void connect().catch((cause: unknown) => {
      if (!cancelled) {
        setStatus("error");
        setError(errorMessage(cause));
      }
    });
    return () => {
      cancelled = true;
      teardown?.();
    };
  }, [device.id]);

  return (
    <section aria-label="远程终端" className="min-w-0 overflow-hidden rounded border border-subtle">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle bg-surface-2 px-4 py-3">
        <div>
          <h2 className="text-14 font-medium">
            终端{" "}
            <span className="font-mono ml-2 text-12 text-secondary">
              {device.username}@{device.hostname}
            </span>
          </h2>
          <p role="status" className="mt-1 text-12 text-secondary">
            {
              {
                connecting: "正在连接…",
                open: "已连接 · 可直接输入命令，Ctrl+C 中断",
                closed: "连接已结束",
                error: "连接已中断",
              }[status]
            }
          </p>
        </div>
        <button type="button" onClick={onClose} className="rounded border border-subtle px-3 py-1.5 text-13">
          关闭终端
        </button>
      </div>
      {error && (
        <p role="alert" className="px-4 py-2 text-13 text-danger-primary">
          {error}
        </p>
      )}
      <div className="h-96 min-w-0 bg-[#101318] p-3">
        <div ref={containerRef} aria-label={`${device.hostname} 交互终端`} className="h-full min-w-0" />
      </div>
    </section>
  );
}
