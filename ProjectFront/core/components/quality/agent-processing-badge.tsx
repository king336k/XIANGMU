// SPDX-License-Identifier: AGPL-3.0-only
import { RotateCw } from "lucide-react";
import type { AgentProcessing } from "./types";
const labels: Record<string, string> = {
  queued: "排队中",
  analysis: "分析中",
  inspect: "排查中",
  repair: "修复中",
  verify: "复测中",
  repaired: "已修复",
  verified: "复核通过",
  unresolved: "未解决",
  interrupted: "已中断",
};
export function AgentProcessingBadge({
  value,
  availability,
  showEmpty = false,
  onClick,
}: {
  value?: AgentProcessing | null;
  availability?: { state: "offline" | "conflict" | "missing" | "ready"; summary?: string } | null;
  showEmpty?: boolean;
  onClick?: () => void;
}) {
  if (!value && !showEmpty) return null;
  const state =
    value?.state ||
    (availability?.state === "conflict"
      ? "conflict"
      : availability && availability.state !== "ready"
        ? "offline"
        : "idle");
  const label = value
    ? labels[value.state] || "状态待确认"
    : state === "conflict"
      ? "接入异常"
      : state === "offline"
        ? "待连接"
        : "未开始";
  const busy = ["queued", "analysis", "inspect", "repair", "verify"].includes(state);
  const tone = busy
    ? "border-accent-subtle bg-accent-subtle text-accent-primary"
    : ["repaired", "verified"].includes(state)
      ? "border-success-subtle bg-success-subtle text-success-primary"
      : state === "interrupted"
        ? "border-danger-subtle bg-danger-subtle text-danger-primary"
        : state === "idle"
          ? "border-subtle bg-layer-1 text-secondary"
          : "border-warning-subtle bg-warning-subtle text-warning-primary";
  const content = (
    <>
      {busy ? (
        <RotateCw aria-hidden="true" className="size-3 animate-spin motion-reduce:animate-none" />
      ) : (
        <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      )}
      Agent · {label}
    </>
  );
  const title = value?.summary || availability?.summary || "查看 Agent 现场处理";
  const className = `inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-11 font-medium whitespace-nowrap ${tone}`;
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Agent：${label}`}
      title={title}
      className={`${className} focus-visible:outline-accent-primary min-h-5 cursor-pointer hover:brightness-95 focus-visible:outline-2`}
    >
      {content}
    </button>
  ) : (
    <span role="status" aria-label={`Agent：${label}`} title={title} className={className}>
      {content}
    </span>
  );
}
