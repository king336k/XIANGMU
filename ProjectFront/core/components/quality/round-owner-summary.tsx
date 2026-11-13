// SPDX-License-Identifier: AGPL-3.0-only
import { OwnerSummary } from "./owner-summary";
import { qualityOwnerMetrics } from "./owner-metrics";
export function RoundOwnerSummary({
  base,
  planId,
  verificationId,
  mode = "cases",
}: {
  base: string;
  planId?: string;
  verificationId?: string;
  mode?: "manual" | "cases";
}) {
  const params = new URLSearchParams(planId ? { plan_id: planId } : { verification_id: verificationId || "" });
  const metrics = qualityOwnerMetrics.filter(
    (item) => item.key.startsWith(mode === "manual" ? "manual_" : "summary_") && item.key !== "manual_execution_count"
  );
  return (
    <details className="rounded border border-subtle p-3">
      <summary className="cursor-pointer text-13">本轮执行人</summary>
      <div className="mt-3">
        <OwnerSummary endpoint={`${base}owner-statistics/`} source="quality" params={params} metrics={metrics} />
      </div>
    </details>
  );
}
