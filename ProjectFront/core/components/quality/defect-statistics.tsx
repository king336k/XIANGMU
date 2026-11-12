// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Distribution, TrendChart } from "./statistics-display";
import { qualityApi, errorMessage } from "./api";
import { statusNames, severityNames } from "./types";
import { DefectStatisticsDetails } from "./defect-statistics-details";
import type { DefectStatisticSelection } from "./defect-statistics-details";
import { defectReport } from "./defect-report";
import type { DefectStatisticsData } from "./defect-report";

const statusColors: Record<string, string> = {
  open: "var(--text-color-warning-primary)",
  in_progress: "var(--text-color-accent-primary)",
  resolved: "var(--text-color-warning-primary)",
  closed: "var(--text-color-success-primary)",
};
const categoryNames: Record<string, string> = {
  UploadError: "上传异常",
  DataAnomaly: "数据异常",
  ValidationFailed: "质检未通过",
  TimestampAnomaly: "时间异常",
  Other: "其他上报",
  daq_incident: "启动或录制异常",
  test: "测试发现",
  manual: "平台新建",
};
const severityColors: Record<string, string> = {
  critical: "var(--text-color-danger-primary)",
  major: "var(--text-color-warning-primary)",
  minor: "var(--text-color-accent-primary)",
  trivial: "var(--text-color-secondary)",
};

export function DefectStatistics({
  base,
  params,
  onOpenDefect,
}: {
  base: string;
  params: URLSearchParams;
  onFilter?: (key: string, value: string) => void;
  onOpenDefect?: (id: string) => void;
}) {
  const [detail, setDetail] = useState<DefectStatisticSelection>();
  const query = new URLSearchParams(params);
  for (const key of ["page", "per_page", "tab", "panel", "layout", "saved_view", "defect", "create"]) query.delete(key);
  const { data, error } = useSWR(
    `${base}defect-statistics/?${query}`,
    (url: string) => qualityApi.read<DefectStatisticsData>(url),
    { refreshInterval: 15000, revalidateOnMount: true }
  );
  if (error)
    return (
      <p role="alert" className="rounded-md border border-danger-subtle p-4 text-13 text-danger-primary">
        {errorMessage(error)}
      </p>
    );
  if (!data)
    return (
      <p role="status" className="py-8 text-13 text-secondary">
        正在统计筛选结果…
      </p>
    );
  const report = defectReport(data);
  const groups = Object.keys(statusNames).map((value) => ({
    value,
    count: data.by_status.find((row) => row.value === value)?.count ?? 0,
  }));
  return (
    <section className="space-y-5" aria-label="缺陷统计报表">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-16 font-semibold">缺陷概览</h2>
        <span className="text-12 text-secondary">当前筛选范围 · 不受分页影响</span>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(
          [
            { title: "全部缺陷", value: data.total, caption: "当前范围", filters: {}, count: data.total },
            {
              title: "未关闭",
              value: data.unclosed,
              caption: "含待处理、处理中和待回归",
              filters: { exclude_status: "closed" },
              count: data.unclosed,
            },
            {
              title: "待回归",
              value: report.awaitingRegression,
              caption: "已修复，等待验证",
              filters: { status: "resolved" },
              count: report.awaitingRegression,
            },
            {
              title: "已关闭",
              value: report.closed,
              caption: `关闭率 ${report.closedPercent}%`,
              filters: { status: "closed" },
              count: report.closed,
            },
          ] as {
            title: string;
            value: number | string;
            caption: string;
            filters: Record<string, string>;
            count: number;
          }[]
        ).map((item) => (
          <button
            type="button"
            key={item.title}
            aria-label={`查看${item.title}明细`}
            onClick={() =>
              setDetail({
                title: item.title,
                filters: item.filters,
                expectedCount: item.count,
              })
            }
            className="focus-visible:outline-accent-primary rounded-md border border-subtle px-4 py-3 text-left hover:bg-layer-1 focus-visible:outline-2"
          >
            <p className="text-12 text-secondary">{item.title}</p>
            <p
              className={`my-2 text-24 font-semibold tabular-nums ${item.title === "已关闭" ? "text-success-primary" : item.title === "未关闭" || item.title === "待回归" ? "text-warning-primary" : "text-accent-primary"}`}
            >
              {item.value}
            </p>
            <p className="text-11 text-tertiary">{item.caption}</p>
          </button>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Distribution
          title="状态分布"
          rows={groups.map((row) => ({
            key: row.value,
            name: statusNames[row.value],
            count: row.count,
            color: statusColors[row.value],
          }))}
          onSelect={(value) =>
            setDetail({
              title: statusNames[value],
              filters: { status: value },
              expectedCount: data.by_status.find((row) => row.value === value)?.count,
            })
          }
        />
        <Distribution
          title="严重程度"
          rows={Object.keys(severityNames).map((value) => ({
            key: value,
            name: severityNames[value],
            count: data.by_severity.find((row) => row.value === value)?.count ?? 0,
            color: severityColors[value],
          }))}
          onSelect={(value) =>
            setDetail({
              title: severityNames[value],
              filters: { severity: value },
              expectedCount: data.by_severity.find((row) => row.value === value)?.count,
            })
          }
        />
      </div>
      {data.by_category && (
        <Distribution
          title="异常来源与类别"
          rows={data.by_category.map((row, index) => ({
            key: row.value,
            name: categoryNames[row.value] || "其他上报",
            count: row.count,
            color: [
              "var(--text-color-accent-primary)",
              "var(--text-color-success-primary)",
              "var(--text-color-warning-primary)",
              "var(--text-color-warning-primary)",
            ][index % 4],
          }))}
          onSelect={(value) =>
            setDetail({
              title: categoryNames[value] || "其他上报",
              filters: { category: value },
              expectedCount: data.by_category?.find((row) => row.value === value)?.count,
            })
          }
        />
      )}
      {!!data.stage_durations?.length && (
        <section className="rounded-md border border-subtle p-4">
          <div className="flex flex-wrap justify-between gap-2">
            <h3 className="text-14 font-medium">处理时效</h3>
            <span className="text-12 text-secondary">尚未开始处理 {data.response_pending ?? 0} 条</span>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {data.stage_durations.map((row) => (
              <div key={row.key} className="rounded bg-layer-1 p-3">
                <p className="text-12 text-secondary">{row.name}</p>
                <p className="my-1 text-18 font-semibold tabular-nums">
                  {row.average_hours === null ? "—" : `${row.average_hours} 小时`}
                </p>
                <p className="text-11 text-secondary">平均耗时 · {row.count} 个有效样本</p>
              </div>
            ))}
          </div>
          <details className="mt-3 text-12 text-secondary">
            <summary className="cursor-pointer">统计口径</summary>
            <p className="mt-2">{data.stage_scope}</p>
          </details>
        </section>
      )}
      <TrendChart
        title={`近30天新增 · ${report.recentTotal} 条 · 按创建日期（北京时间）`}
        data={report.trend.map((row) => ({ key: row.date, date: row.date, name: row.name, count: row.count }))}
        series={[{ key: "count", label: "新增缺陷", color: "var(--text-color-accent-primary)" }]}
        onSelect={(date) =>
          setDetail({
            title: `${date} 新增`,
            filters: { created_after: date, created_before: date },
            expectedCount: report.trend.find((row) => row.date === date)?.count,
          })
        }
      />
      <p className="text-11 text-tertiary">点击数字或图表，查看对应缺陷明细。</p>
      {detail && (
        <DefectStatisticsDetails
          base={base}
          params={params}
          selection={detail}
          onClose={() => setDetail(undefined)}
          onOpenDefect={onOpenDefect}
        />
      )}
    </section>
  );
}
