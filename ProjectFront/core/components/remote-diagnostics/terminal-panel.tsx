// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { remoteDiagnosticsBase } from "./types";
import type { RemoteDevice, TerminalStatus, TerminalTarget, TerminalSession, RobotTarget } from "./types";
import { TerminalConnection } from "./terminal-connection";

export function TerminalPanel({
  device,
  robot,
  onClose,
}: {
  device: RemoteDevice;
  robot?: RobotTarget;
  onClose: () => void;
}) {
  const [target, setTarget] = useState<TerminalTarget>("operator");
  const [boundRobot, setBoundRobot] = useState<string | null>(null);
  const [session, setSession] = useState<TerminalSession | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<TerminalStatus>("connecting");
  const [error, setError] = useState("");
  const robotRevision = robot?.target_revision || "";
  const robotKey = JSON.stringify([robotRevision, robot?.username || "", robot?.host || ""]);
  const robotAvailable = robot?.connected === true && !!robot.username && !!robot.host && !!robotRevision.trim();
  const targetValid = target !== "robot" || (robotAvailable && boundRobot === robotKey);
  const expectedRevision = target === "robot" ? robotRevision : undefined;
  const sessionIdentity = session?.identity || session?.target_identity;

  useEffect(() => {
    if (!targetValid) {
      setStatus("closed");
      setSession(null);
      setError("机器人连接已变化，请重新连接终端。");
      return;
    }
    setStatus("connecting");
    setSession(null);
    setError("");
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
        },
        (value) => {
          if (!cancelled) setSession(value);
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
      void connection.open(device.id, terminal.cols, terminal.rows, target, expectedRevision);
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
  }, [device.id, target, targetValid, expectedRevision]);

  return (
    <section aria-label="远程终端" className="min-w-0 overflow-hidden rounded border border-subtle">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle bg-surface-2 px-4 py-3">
        <div>
          <h2 className="text-14 font-medium">
            终端{" "}
            <span className="font-mono ml-2 text-12 text-secondary">
              {sessionIdentity?.username || (target === "operator" ? device.username : "身份待确认")}@
              {sessionIdentity?.host || (target === "operator" ? device.ip_address || "IP待确认" : "IP待确认")}
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
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-pressed={target === "operator"}
            onClick={() => setTarget("operator")}
            className="rounded border border-subtle px-3 py-1.5 text-13"
          >
            采集电脑
          </button>
          <button
            type="button"
            aria-pressed={target === "robot"}
            disabled={!robotAvailable}
            title={
              !robotAvailable
                ? "请先在DAQ连接机器人"
                : `${robot?.username || "身份待确认"}@${robot?.host || "IP待确认"}`
            }
            onClick={() => {
              setBoundRobot(robotKey);
              setTarget("robot");
            }}
            className="rounded border border-subtle px-3 py-1.5 text-13 disabled:opacity-40"
          >
            {target === "robot" && !targetValid ? "重新连接机器人" : "机器人"}
          </button>
          <button type="button" onClick={onClose} className="rounded border border-subtle px-3 py-1.5 text-13">
            关闭终端
          </button>
        </div>
      </div>
      {!robotAvailable && <p className="px-4 py-2 text-12 text-secondary">请先在DAQ连接机器人</p>}
      {error && (
        <p role="alert" className="px-4 py-2 text-13 text-danger-primary">
          {error}
        </p>
      )}
      <div className="h-96 min-w-0 bg-[#101318] p-3">
        <div
          ref={containerRef}
          aria-label={`${target === "robot" ? "机器人" : "采集电脑"}交互终端`}
          className="h-full min-w-0"
        />
      </div>
    </section>
  );
}
