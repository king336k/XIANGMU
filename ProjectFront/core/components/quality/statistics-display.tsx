// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { BarChart3, ChartPie, Table2, ChevronDown, Check, ChartNoAxesCombined } from "lucide-react";
import { CustomMenu } from "@plane/ui";
import { PieChart } from "@plane/propel/charts/pie-chart";
import { AreaChart } from "@plane/propel/charts/area-chart";
import { BarChart } from "@plane/propel/charts/bar-chart";

export type StatisticsMode = "bar" | "donut" | "line" | "table";
const modes = [
  { key: "bar", title: "条形图", icon: BarChart3 },
  { key: "donut", title: "环形图", icon: ChartPie },
  { key: "line", title: "折线图", icon: ChartNoAxesCombined },
  { key: "table", title: "数据表", icon: Table2 },
] as const;
export function StatisticsDisplay({
  value,
  onChange,
  options = ["bar", "donut", "table"],
}: {
  value: StatisticsMode;
  onChange: (mode: StatisticsMode) => void;
  options?: StatisticsMode[];
}) {
  const current = modes.find((mode) => mode.key === value)!;
  return (
    <CustomMenu
      placement="bottom-end"
      closeOnSelect
      customButton={
        <span className="flex shrink-0 items-center gap-2 rounded-md border border-subtle bg-surface-1 px-3 py-1.5 text-12 whitespace-nowrap text-secondary">
          <current.icon className="size-3.5" />
          显示方式
          <ChevronDown className="size-3" />
        </span>
      }
    >
      {modes
        .filter((mode) => options.includes(mode.key))
        .map((mode) => (
          <CustomMenu.MenuItem key={mode.key} onClick={() => onChange(mode.key)}>
            <mode.icon className="size-4" />
            {mode.key === "bar" && options.includes("line") ? "柱形图" : mode.title}
            {value === mode.key && <Check className="ml-auto size-3.5" aria-label="当前显示方式" />}
          </CustomMenu.MenuItem>
        ))}
    </CustomMenu>
  );
}
export type StatisticRow = { key: string; name: string; count: number; color: string };
export function Distribution({
  title,
  rows,
  onSelect,
}: {
  title: string;
  rows: StatisticRow[];
  onSelect?: (key: string) => void;
}) {
  const [mode, setMode] = useState<StatisticsMode>("bar");
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  return (
    <section aria-label={title} className="min-w-0 space-y-4 rounded-md border border-subtle p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-14 font-medium">{title}</h3>
        <StatisticsDisplay value={mode} onChange={setMode} />
      </div>
      {mode === "donut" && total > 0 && (
        <PieChart
          className="h-48 w-full"
          data={rows.filter((row) => row.count).map((row) => ({ key: row.key, name: row.name, count: row.count }))}
          dataKey="count"
          cells={rows.filter((row) => row.count).map((row) => ({ key: row.key, fill: row.color }))}
          innerRadius="65%"
          outerRadius="90%"
          showLabel={false}
          centerLabel={{ text: total, fill: "var(--text-color-primary)" }}
          tooltipLabel="数量"
        />
      )}
      {mode === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-12">
            <thead className="text-secondary">
              <tr>
                <th className="font-normal pb-2">分类</th>
                <th className="font-normal text-right">数量</th>
                <th className="font-normal text-right">占比</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-t border-subtle">
                  <td className="py-2">
                    <button
                      type="button"
                      disabled={!onSelect || !row.count}
                      onClick={() => onSelect?.(row.key)}
                      className="hover:text-accent-primary"
                    >
                      {row.name}
                    </button>
                  </td>
                  <td className="text-right tabular-nums">{row.count}</td>
                  <td className="text-right tabular-nums">{total ? Math.round((row.count / total) * 100) : 0}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((row) => (
            <button
              key={row.key}
              type="button"
              disabled={!onSelect || !row.count}
              onClick={() => onSelect?.(row.key)}
              className="block w-full rounded text-left hover:bg-layer-1"
            >
              <span className="flex items-center gap-2 text-12">
                <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: row.color }} />
                <span className="flex-1">{row.name}</span>
                <strong className="tabular-nums">{row.count}</strong>
                <span className="w-10 text-right text-secondary">
                  {total ? Math.round((row.count / total) * 100) : 0}%
                </span>
              </span>
              {mode === "bar" && (
                <span className="mt-2 block h-2 overflow-hidden rounded bg-layer-1">
                  <span
                    className="block h-full rounded"
                    style={{ width: `${total ? (row.count / total) * 100 : 0}%`, backgroundColor: row.color }}
                  />
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {total === 0 && <p className="text-12 text-tertiary">当前范围暂无数据。</p>}
    </section>
  );
}
export function TrendChart({
  title,
  data,
  series,
  onSelect,
}: {
  title: string;
  data: ({ name: string; key: string } & Record<string, string | number>)[];
  series: { key: string; label: string; color: string }[];
  onSelect?: (rowKey: string, seriesKey: string) => void;
}) {
  const [mode, setMode] = useState<StatisticsMode>("line");
  const max = Math.max(1, ...data.map((row) => series.reduce((total, item) => total + Number(row[item.key] || 0), 0)));
  const axis = {
    xAxis: { key: "name" },
    yAxis: { key: series[0].key, allowDecimals: false, domain: [0, max] as [number, number] },
    margin: { top: 10, right: 12, left: 0, bottom: 0 },
    tickCount: { x: 6, y: 4 },
  };
  return (
    <section aria-label={title} className="min-w-0 space-y-4 rounded-md border border-subtle p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-14 font-medium">{title}</h3>
        <StatisticsDisplay value={mode} onChange={setMode} options={["line", "bar", "table"]} />
      </div>
      {mode === "table" ? (
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-left text-12">
            <thead>
              <tr>
                <th className="py-2">日期</th>
                {series.map((item) => (
                  <th key={item.key} className="text-right">
                    {item.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.key} className="border-t border-subtle">
                  <td className="py-2">{row.name}</td>
                  {series.map((item) => (
                    <td key={item.key} className="text-right tabular-nums">
                      {onSelect ? (
                        <button
                          type="button"
                          className="text-accent-primary hover:underline"
                          onClick={() => onSelect(row.key, item.key)}
                          aria-label={`查看${row.name}${item.label}明细`}
                        >
                          {row[item.key]}
                        </button>
                      ) : (
                        row[item.key]
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : mode === "bar" ? (
        <BarChart
          className="h-60 w-full"
          data={data}
          {...axis}
          bars={series.map((item) => ({
            key: item.key,
            label: item.label,
            fill: item.color,
            textClassName: "",
            stackId: item.key,
          }))}
        />
      ) : (
        <AreaChart
          className="h-60 w-full"
          data={data}
          {...axis}
          areas={series.map((item) => ({
            key: item.key,
            label: item.label,
            fill: item.color,
            fillOpacity: 0.06,
            stackId: item.key,
            showDot: data.length < 32,
            smoothCurves: false,
            strokeColor: item.color,
            strokeOpacity: 1,
          }))}
        />
      )}
      {onSelect && mode !== "table" && (
        <details className="text-12 text-secondary">
          <summary className="cursor-pointer">查看数据明细</summary>
          <div className="mt-3 max-h-48 space-y-2 overflow-auto">
            {data.map((row) => (
              <div key={row.key} className="flex flex-wrap items-center gap-3">
                <span>{row.name}</span>
                {series.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className="text-accent-primary hover:underline"
                    onClick={() => onSelect(row.key, item.key)}
                  >
                    {item.label} {row[item.key]}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </details>
      )}
      <div className="flex flex-wrap gap-4 text-11 text-secondary">
        {series.map((item) => (
          <span key={item.key} className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ backgroundColor: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
    </section>
  );
}
