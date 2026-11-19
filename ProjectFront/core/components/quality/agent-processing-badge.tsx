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
export function AgentProcessingBadge({ value }: { value?: AgentProcessing | null }) {
  if (!value) return null;
  const busy = ["queued", "analysis", "inspect", "repair", "verify"].includes(value.state);
  const tone = busy
    ? "border-accent-subtle bg-accent-subtle text-accent-primary"
    : ["repaired", "verified"].includes(value.state)
      ? "border-success-subtle bg-success-subtle text-success-primary"
      : value.state === "interrupted"
        ? "border-danger-subtle bg-danger-subtle text-danger-primary"
        : "border-warning-subtle bg-warning-subtle text-warning-primary";
  return (
    <span
      role="status"
      aria-label={`Agent：${labels[value.state] || "状态待确认"}`}
      title={value.summary || "Agent 现场处理状态"}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-11 font-medium whitespace-nowrap ${tone}`}
    >
      {busy ? (
        <RotateCw aria-hidden="true" className="size-3 animate-spin motion-reduce:animate-none" />
      ) : (
        <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      )}
      {labels[value.state] || "状态待确认"}
    </span>
  );
}
