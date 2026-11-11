/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { AnalyticsDetails } from "../analytics-details";
import { useMemo, useState } from "react";
import type { ColumnDef, Row, RowData, Table } from "@tanstack/react-table";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { useTheme } from "next-themes";
import useSWR from "swr";
// plane package imports
import { Download } from "lucide-react";
import type { ChartXAxisDateGrouping } from "@plane/constants";
import { ANALYTICS_X_AXIS_VALUES, ANALYTICS_Y_AXIS_VALUES, CHART_COLOR_PALETTES, EChartModels } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { PieChart } from "@plane/propel/charts/pie-chart";
import { StatisticsDisplay } from "@/components/quality/statistics-display";
import type { StatisticsMode } from "@/components/quality/statistics-display";
import { BarChart } from "@plane/propel/charts/bar-chart";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import type { TBarItem, TChart, TChartDatum, ChartXAxisProperty, ChartYAxisMetric } from "@plane/types";
// plane web components
import { generateExtendedColors, parseChartData } from "@/components/chart/utils";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
import { useProjectState } from "@/hooks/store/use-project-state";
import { AnalyticsService } from "@/services/analytics.service";
import { exportCSV } from "../export";
import { DataTable } from "../insight-table/data-table";
import { ChartLoader } from "../loaders";
import { generateBarColor } from "./utils";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    export: {
      key: string;
      value: (row: Row<TData>) => string | number;
      label?: string;
    };
  }
}

interface Props {
  x_axis: ChartXAxisProperty;
  y_axis: ChartYAxisMetric;
  group_by?: ChartXAxisProperty;
  x_axis_date_grouping?: ChartXAxisDateGrouping;
}

const analyticsService = new AnalyticsService();
const PriorityChart = observer(function PriorityChart(props: Props) {
  const { x_axis, y_axis, group_by } = props;
  const { t } = useTranslation();
  const [mode, setMode] = useState<StatisticsMode>("bar");
  const [detail, setDetail] = useState<{ key: string; title: string; group?: string }>();
  const openDetail = (row: TChartDatum, group?: string) =>
    setDetail({ key: String(row.key), title: String(row.name), group });
  // store hooks
  const { selectedDuration, selectedProjects, selectedCycle, selectedModule, isPeekView, isEpic } = useAnalytics();
  const { workspaceStates } = useProjectState();
  const { resolvedTheme } = useTheme();
  // router
  const params = useParams();
  const workspaceSlug = params.workspaceSlug.toString();

  const { data: priorityChartData, isLoading: priorityChartLoading } = useSWR(
    `customized-insights-chart-${workspaceSlug}-${selectedDuration}-
    ${selectedProjects}-${selectedCycle}-${selectedModule}-${props.x_axis}-${props.y_axis}-${props.group_by}-${isPeekView}-${isEpic}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<TChart>(
        workspaceSlug,
        "custom-work-items",
        {
          // date_filter: selectedDuration,
          ...(selectedProjects?.length > 0 && { project_ids: selectedProjects?.join(",") }),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
          ...(isEpic ? { epic: true } : {}),
          ...props,
        },
        isPeekView
      )
  );
  const parsedData = useMemo(
    () =>
      priorityChartData && parseChartData(priorityChartData, props.x_axis, props.group_by, props.x_axis_date_grouping),
    [priorityChartData, props.x_axis, props.group_by, props.x_axis_date_grouping]
  );
  const chart_model = props.group_by ? EChartModels.STACKED : EChartModels.BASIC;

  const bars: TBarItem<string>[] = useMemo(() => {
    if (!parsedData) return [];
    let parsedBars: TBarItem<string>[];
    const schemaKeys = Object.keys(parsedData.schema);
    const baseColors = CHART_COLOR_PALETTES[0]?.[resolvedTheme === "dark" ? "dark" : "light"];
    const extendedColors = generateExtendedColors(baseColors ?? [], schemaKeys.length);
    if (chart_model === EChartModels.BASIC) {
      parsedBars = [
        {
          key: "count",
          label: "数量",
          stackId: "bar-one",
          fill: (payload) => generateBarColor(payload.key, { x_axis, y_axis, group_by }, baseColors, workspaceStates),
          textClassName: "",
          showPercentage: false,
          showTopBorderRadius: () => true,
          showBottomBorderRadius: () => true,
        },
      ];
    } else if (chart_model === EChartModels.STACKED && parsedData.schema) {
      const parsedExtremes: {
        [key: string]: {
          top: string | null;
          bottom: string | null;
        };
      } = {};
      parsedData.data.forEach((datum) => {
        let top = null;
        let bottom = null;
        for (let i = 0; i < schemaKeys.length; i++) {
          const key = schemaKeys[i];
          if (datum[key] === 0) continue;
          if (!bottom) bottom = key;
          top = key;
        }
        parsedExtremes[datum.key] = { top, bottom };
      });

      parsedBars = schemaKeys.map((key, index) => ({
        key: key,
        label: parsedData.schema[key],
        stackId: "bar-one",
        fill: extendedColors[index],
        textClassName: "",
        showPercentage: false,
        showTopBorderRadius: (value, payload: TChartDatum) => parsedExtremes[payload.key].top === value,
        showBottomBorderRadius: (value, payload: TChartDatum) => parsedExtremes[payload.key].bottom === value,
      }));
    } else {
      parsedBars = [];
    }
    return parsedBars;
  }, [chart_model, group_by, parsedData, resolvedTheme, workspaceStates, x_axis, y_axis]);

  const yAxisLabel = useMemo(
    () => ANALYTICS_Y_AXIS_VALUES.find((item) => item.value === props.y_axis)?.label ?? props.y_axis,
    [props.y_axis]
  );
  const xAxisLabel = useMemo(
    () => ANALYTICS_X_AXIS_VALUES.find((item) => item.value === props.x_axis)?.label ?? props.x_axis,
    [props.x_axis]
  );

  const defaultColumns: ColumnDef<TChartDatum>[] = useMemo(
    () => [
      {
        accessorKey: "name",
        header: () => xAxisLabel,
        meta: {
          export: {
            key: xAxisLabel,
            value: (row) => row.original.name,
            label: xAxisLabel,
          },
        },
      },
      {
        accessorKey: "count",
        header: () => <div className="text-right">数量</div>,
        cell: ({ row }) => (
          <button
            type="button"
            className="block w-full text-right text-accent-primary hover:underline"
            onClick={() => openDetail(row.original)}
          >
            {row.original.count}
          </button>
        ),
        meta: {
          export: {
            key: "Count",
            value: (row) => row.original.count,
            label: "数量",
          },
        },
      },
    ],
    [xAxisLabel]
  );

  const columns: ColumnDef<TChartDatum>[] = useMemo(
    () =>
      parsedData
        ? Object.keys(parsedData?.schema ?? {}).map((key) => ({
            accessorKey: key,
            header: () => <div className="text-right">{parsedData.schema[key]}</div>,
            cell: ({ row }) => (
              <button
                type="button"
                className="block w-full text-right text-accent-primary hover:underline"
                onClick={() => openDetail(row.original, key)}
              >
                {row.original[key]}
              </button>
            ),
            meta: {
              export: {
                key,
                value: (row) => row.original[key],
                label: parsedData.schema[key],
              },
            },
          }))
        : [],
    [parsedData]
  );

  return (
    <>
      <div className="flex flex-col gap-6">
        {priorityChartLoading ? (
          <ChartLoader />
        ) : parsedData?.data && parsedData.data.length > 0 ? (
          <>
            <div className="flex justify-end">
              <StatisticsDisplay
                value={mode}
                onChange={setMode}
                options={group_by ? ["bar", "table"] : ["bar", "donut", "table"]}
              />
            </div>
            {mode === "donut" && !group_by && (
              <PieChart
                className="h-[340px] w-full"
                data={parsedData.data}
                dataKey="count"
                cells={parsedData.data.map((row, index) => ({
                  key: String(row.key),
                  fill: generateExtendedColors(
                    CHART_COLOR_PALETTES[0]?.[resolvedTheme === "dark" ? "dark" : "light"] || [],
                    parsedData.data.length
                  )[index],
                }))}
                innerRadius="60%"
                showLabel={false}
                tooltipLabel="工作项数量"
              />
            )}
            {mode !== "table" && (mode !== "donut" || group_by) && (
              <BarChart
                className="h-[370px] w-full"
                data={parsedData.data}
                bars={bars}
                margin={{
                  bottom: 30,
                }}
                xAxis={{
                  key: "name",
                  label: xAxisLabel.replace("_", " "),
                  dy: 30,
                }}
                yAxis={{
                  key: "count",
                  label: t("common.no_of", { entity: yAxisLabel.replace("_", " ") }),
                  offset: -60,
                  dx: -26,
                }}
              />
            )}
            {mode !== "table" && (
              <details className="text-12 text-secondary">
                <summary className="cursor-pointer">查看数据明细</summary>
                <div className="mt-3 max-h-48 space-y-2 overflow-auto">
                  {parsedData.data.map((row) => (
                    <div key={String(row.key)} className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        className="text-accent-primary hover:underline"
                        onClick={() => openDetail(row)}
                      >
                        {row.name} · {row.count}
                      </button>
                      {group_by &&
                        Object.entries(parsedData.schema).map(([key, label]) => (
                          <button
                            key={key}
                            type="button"
                            className="text-accent-primary hover:underline"
                            onClick={() => openDetail(row, key)}
                          >
                            {label} {row[key] || 0}
                          </button>
                        ))}
                    </div>
                  ))}
                </div>
              </details>
            )}
            {mode === "table" && (
              <DataTable
                data={parsedData.data}
                columns={[...defaultColumns, ...columns]}
                searchPlaceholder={`${parsedData.data.length} ${xAxisLabel}`}
                actions={(table: Table<TChartDatum>) => (
                  <Button
                    variant="secondary"
                    prependIcon={<Download className="h-3.5 w-3.5" />}
                    onClick={() => exportCSV(table.getRowModel().rows, [...defaultColumns, ...columns], workspaceSlug)}
                  >
                    <div>{t("exporter.csv.short_description")}</div>
                  </Button>
                )}
              />
            )}
          </>
        ) : (
          <EmptyStateCompact
            assetKey="unknown"
            assetClassName="size-20"
            rootClassName="border border-subtle px-5 py-10 md:py-20 md:px-20"
            title={t("workspace_empty_state.analytics_work_items.title")}
          />
        )}
      </div>
      {detail && (
        <AnalyticsDetails
          title={detail.title}
          metric="total_work_items"
          isPeekView={isPeekView}
          filters={{
            ...(selectedProjects?.length ? { project_ids: selectedProjects.join(",") } : {}),
            ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
            ...(selectedModule ? { module_id: selectedModule } : {}),
            dimension: String(x_axis),
            dimension_value: detail.key,
            ...(detail.group && group_by ? { group_dimension: String(group_by), group_value: detail.group } : {}),
          }}
          onClose={() => setDetail(undefined)}
        />
      )}
    </>
  );
});

export default PriorityChart;
