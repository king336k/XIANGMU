// SPDX-License-Identifier: AGPL-3.0-only
import { resultNames, statusNames, severityNames } from "./types";
const colors: Record<string, string> = {
  draft: "border-subtle bg-layer-1 text-secondary",
  cancelled: "border-subtle bg-layer-1 text-secondary",
  archived: "border-subtle bg-layer-1 text-secondary",
  open: "border-warning-subtle bg-warning-subtle text-warning-primary",
  in_progress: "border-accent-subtle-1 bg-accent-subtle text-accent-primary",
  resolved: "border-warning-subtle bg-warning-subtle text-warning-primary",
  passed: "border-success-subtle bg-success-subtle text-success-primary",
  closed: "border-success-subtle bg-success-subtle text-success-primary",
  failed: "border-danger-subtle bg-danger-subtle text-danger-primary",
  blocked: "border-danger-subtle bg-danger-subtle text-danger-primary",
  inconclusive: "border-warning-subtle bg-warning-subtle text-warning-primary",
  critical: "border-danger-subtle bg-danger-subtle text-danger-primary",
  major: "border-warning-subtle bg-warning-subtle text-warning-primary",
  minor: "border-accent-subtle-1 bg-accent-subtle text-accent-primary",
  trivial: "border-subtle bg-layer-1 text-secondary",
  pending: "border-warning-subtle bg-warning-subtle text-warning-primary",
  review: "border-warning-subtle bg-warning-subtle text-warning-primary",
  ready: "border-accent-subtle-1 bg-accent-subtle text-accent-primary",
  running: "border-accent-subtle-1 bg-accent-subtle text-accent-primary",
  approved: "border-accent-subtle-1 bg-accent-subtle text-accent-primary",
  completed: "border-success-subtle bg-success-subtle text-success-primary",
  returned: "border-warning-subtle bg-warning-subtle text-warning-primary",
};
export function Badge({
  value,
  label,
  variant = "default",
}: {
  value: string;
  label?: string;
  variant?: "default" | "plain";
}) {
  return (
    <span
      className={
        variant === "plain"
          ? `font-normal inline-flex items-center gap-1.5 text-11 whitespace-nowrap ${
              colors[value]
                ?.split(" ")
                .filter((token) => token.startsWith("text-"))
                .join(" ") || "text-secondary"
            }`
          : `inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-11 font-medium whitespace-nowrap ${colors[value] || "border-subtle bg-layer-1 text-secondary"}`
      }
    >
      <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-current" />
      {label ?? resultNames[value] ?? statusNames[value] ?? severityNames[value] ?? value}
    </span>
  );
}
