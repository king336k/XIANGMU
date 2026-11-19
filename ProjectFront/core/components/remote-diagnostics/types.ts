// SPDX-License-Identifier: AGPL-3.0-only
export type RemoteDevice = {
  id: string;
  username: string;
  hostname: string;
  ip_address?: string;
  name: string;
  online: boolean;
  last_seen_at: string | null;
  project_id: string;
  workspace_slug: string;
  can_connect: boolean;
  capabilities: Record<string, unknown>;
};

export type TerminalStatus = "connecting" | "open" | "closed" | "error";
export type TerminalTarget = "operator" | "robot";
export type RobotTarget = { connected?: boolean; username?: string; host?: string; target_revision?: string };
export type TerminalSession = {
  id: string;
  status: string;
  target?: TerminalTarget;
  identity?: { username?: string; host?: string };
  target_identity?: { username?: string; host?: string };
  target_revision?: string;
};
export type TerminalSnapshot = {
  id: string;
  status: string;
  events: { seq: number; source_id?: string; data: string }[];
  cursor: number;
  error?: string;
} & TerminalSession;

export type AgentRun = {
  id: string;
  status: string;
  mode?: "diagnose" | "repair" | "verify";
  queue?: {
    position?: number | null;
    reason?: "device_busy" | "worker_busy" | "terminal_open" | "transfer_active" | string;
    stage?: "queued" | "analysis" | "inspect" | "repair" | "verify";
    active_count?: number;
  };
  result?: {
    summary?: unknown;
    root_cause?: unknown;
    actions?: unknown;
    verification?: unknown;
    solution?: unknown;
    repaired?: boolean;
    verification_passed?: boolean;
    outcome?: "verified" | "verified_without_repair" | "repaired" | "unresolved";
  } | null;
  error?: string;
};

export const remoteDiagnosticsBase = "/api/quality-auth/remote-diagnostics/";
export const runningAgentStatuses = new Set(["pending", "queued", "running", "starting"]);

export function agentStatusLabel(status: string) {
  return (
    {
      pending: "等待开始",
      queued: "排队中",
      starting: "正在启动",
      running: "诊断中",
      completed: "诊断完成",
      succeeded: "诊断完成",
      failed: "诊断失败",
      cancelled: "已取消",
      timed_out: "诊断超时",
    }[status] || "状态待确认"
  );
}

export function agentRunStatusLabel(run: AgentRun): string {
  if (run.status === "failed") return "处理失败";
  if (run.status === "timed_out") return "处理超时";
  if (run.status === "completed") {
    if (run.result?.repaired === true && run.result.verification_passed === true) return "已修复并复测";
    if (
      ["verified", "verified_without_repair"].includes(run.result?.outcome || "") &&
      run.result?.verification_passed === true
    )
      return "复测通过";
    return "处理完成";
  }
  if (run.status === "queued") {
    const reasons: Record<string, string> = {
      device_busy: "等待采集电脑空闲",
      worker_busy: "等待诊断资源空闲",
      terminal_open: "等待终端关闭",
      transfer_active: "等待文件传输完成",
    };
    const waiting = reasons[run.queue?.reason || ""] || "排队中";
    const position = run.queue?.position;
    return typeof position === "number" && Number.isSafeInteger(position) && position > 0
      ? `${waiting} · 前方 ${position} 个任务`
      : waiting;
  }
  if (run.status === "running") {
    return (
      (
        { analysis: "模型正在分析现场", inspect: "正在诊断", repair: "正在修复", verify: "正在复测" } as Record<
          string,
          string
        >
      )[run.queue?.stage || ""] || "正在处理"
    );
  }
  return agentStatusLabel(run.status);
}

export function agentRunShortLabel(run: AgentRun): string {
  if (["failed", "timed_out", "cancelled"].includes(run.status)) return "已中断";
  if (run.status === "completed" || run.status === "succeeded") {
    if (run.result?.verification_passed === true) {
      if (run.result.repaired === true) return "已修复";
      if (["verified", "verified_without_repair"].includes(run.result.outcome || "")) return "复核通过";
    }
    return "未解决";
  }
  if (["queued", "pending", "starting"].includes(run.status)) return "排队中";
  if (run.status === "running")
    return (
      ({ analysis: "分析中", inspect: "排查中", repair: "修复中", verify: "复测中" } as Record<string, string>)[
        run.queue?.stage || ""
      ] || "排查中"
    );
  return "状态待确认";
}
