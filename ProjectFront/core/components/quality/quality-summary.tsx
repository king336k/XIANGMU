// SPDX-License-Identifier: AGPL-3.0-only
import { Distribution } from "./statistics-display";
import { Badge } from "./shared";
import { resultNames } from "./types";
import type { Report } from "./types";
import { useState } from "react";
import { QualityOverviewDetails } from "./quality-overview-details";
import type { OverviewRecord, OverviewSelection } from "./quality-overview-details";
export function QualitySummary({
  report,
  onNavigate,
  base,
  onOpenRecord,
}: {
  report: Report;
  onNavigate?: (tab: string, result?: string, currentOnly?: boolean) => void;
  base?: string;
  onOpenRecord?: (record: OverviewRecord) => void;
}) {
  const [selection, setSelection] = useState<OverviewSelection | null>(null);
  const open = (kind: OverviewSelection["kind"], title: string, result?: string) => {
    if (base) setSelection({ kind, title, result });
    else
      onNavigate?.(
        kind === "manual" ? "verification-results" : kind === "pending" ? "plans" : kind,
        result,
        kind === "plans" || !!result
      );
  };
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {[
          ["测试用例", report.case_count, "cases"],
          ["有效测试计划", report.plan_count, "plans"],
          ["执行记录", report.execution_count, "executions"],
          ["未关闭缺陷", report.open_defects, "defects"],
          ["已关闭缺陷", report.closed_defects || 0, "defects"],
        ].map(([label, number, tab]) => (
          <button
            type="button"
            key={label}
            disabled={!base && !onNavigate}
            onClick={() =>
              open(tab as OverviewSelection["kind"], String(label), label === "已关闭缺陷" ? "closed" : undefined)
            }
            className="focus-visible:ring-accent-primary rounded-md border border-subtle bg-surface-1 p-4 text-left hover:bg-layer-1 focus-visible:ring-2 focus-visible:outline-none disabled:cursor-default"
          >
            <p className="text-12 text-secondary">{label}</p>
            <p
              className={`mt-2 text-24 font-semibold ${label === "已关闭缺陷" ? "text-success-primary" : label === "未关闭缺陷" ? "text-warning-primary" : "text-accent-primary"}`}
            >
              {number}
            </p>
          </button>
        ))}
      </div>
      <section className="space-y-4">
        <h2 className="text-16 font-semibold">计划执行概况</h2>
        <p className="text-13">
          执行率 {report.summary.execution_rate}% ·{" "}
          <span className={report.summary.pass_rate ? "text-success-primary" : "text-secondary"}>
            通过率 {report.summary.pass_rate}%
          </span>
        </p>
        <div className="h-2 overflow-hidden rounded bg-layer-1">
          <div className="h-full bg-accent-primary" style={{ width: `${report.summary.execution_rate}%` }} />
        </div>
        <Distribution
          title="执行结果分布"
          onSelect={
            base || onNavigate
              ? (value) =>
                  open(
                    value === "pending" ? "pending" : "executions",
                    resultNames[value],
                    value === "pending" ? undefined : value
                  )
              : undefined
          }
          showStatus
          rows={["passed", "failed", "blocked", "inconclusive", "skipped", "pending"].map((key) => ({
            key,
            name: resultNames[key],
            count: Number(report.summary[key as keyof typeof report.summary]) || 0,
            color:
              {
                passed: "var(--text-color-success-primary)",
                failed: "var(--text-color-danger-primary)",
                blocked: "var(--text-color-danger-primary)",
                inconclusive: "var(--text-color-warning-primary)",
                skipped: "var(--text-color-secondary)",
                pending: "var(--text-color-secondary)",
              }[key] || "var(--text-color-secondary)",
          }))}
        />
        <p className="text-13">
          已关联工作项的用例：{report.requirement_linked_cases} / {report.case_count}
        </p>
      </section>
      {report.manual_verification && (
        <section className="space-y-3 rounded-md border border-subtle p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-14 font-semibold">人工验证</h2>
            <button
              type="button"
              disabled={!base && !onNavigate}
              className="focus-visible:ring-accent-primary rounded text-12 text-accent-primary hover:underline focus-visible:ring-2 focus-visible:outline-none disabled:text-secondary"
              onClick={() => open("manual", "人工验证")}
            >
              查看缺陷验证
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge value="neutral" label={`当前 ${report.manual_verification.total} 轮`} />
            <Badge value="passed" label={`通过率 ${report.manual_verification.pass_rate || 0}%`} />
          </div>
          <Distribution
            title="人工验证结果"
            showStatus
            onSelect={
              base || onNavigate ? (value) => open("manual", `人工验证 · ${resultNames[value]}`, value) : undefined
            }
            rows={["passed", "failed", "blocked", "inconclusive", "skipped", "pending"].map((key) => ({
              key,
              name: resultNames[key],
              count: Number(report.manual_verification?.[key as keyof typeof report.manual_verification]) || 0,
              color:
                {
                  passed: "var(--text-color-success-primary)",
                  failed: "var(--text-color-danger-primary)",
                  blocked: "var(--text-color-danger-primary)",
                  inconclusive: "var(--text-color-warning-primary)",
                }[key] || "var(--text-color-secondary)",
            }))}
          />
          <p className="text-12 text-secondary">
            历史实测 {report.manual_execution_count || 0} 次 · 当前每个缺陷取最新有效轮次
          </p>
        </section>
      )}
      <details className="space-y-2 text-12 text-secondary">
        <summary className="cursor-pointer">统计口径</summary>
        {Object.values(report.definitions).map((text) => (
          <p key={text}>{text}</p>
        ))}
      </details>
      {selection && base && (
        <QualityOverviewDetails
          base={base}
          selection={selection}
          onClose={() => setSelection(null)}
          onOpenRecord={onOpenRecord}
        />
      )}
    </div>
  );
}
