/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { AnalyticsDetails } from "../analytics-details";
import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane package imports
import { useTranslation } from "@plane/i18n";
import { TrendChart } from "@/components/quality/statistics-display";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import type { IChartResponse, TChartData } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
// services
import { AnalyticsService } from "@/services/analytics.service";
// plane web components
import AnalyticsSectionWrapper from "../analytics-section-wrapper";
import { ChartLoader } from "../loaders";

const analyticsService = new AnalyticsService();
const CreatedVsResolved = observer(function CreatedVsResolved() {
  const { selectedDuration, selectedProjects, selectedCycle, selectedModule, isPeekView, isEpic } = useAnalytics();
  const params = useParams();
  const { t } = useTranslation();
  const workspaceSlug = params.workspaceSlug.toString();
  const [detail, setDetail] = useState<{ month: string; completed: boolean }>();
  const { data: createdVsResolvedData, isLoading: isCreatedVsResolvedLoading } = useSWR(
    `created-vs-resolved-${workspaceSlug}-${selectedDuration}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${isEpic}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<IChartResponse>(
        workspaceSlug,
        "work-items",
        {
          ...(selectedDuration ? { date_filter: selectedDuration } : {}),
          ...(selectedProjects?.length > 0 && { project_ids: selectedProjects?.join(",") }),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
          ...(isEpic ? { epic: true } : {}),
        },
        isPeekView
      )
  );
  const parsedData: TChartData<string, string>[] = useMemo(() => {
    if (!createdVsResolvedData?.data) return [];
    return createdVsResolvedData.data.map((datum) => ({
      ...datum,
      [datum.key]: datum.count,
      name: renderFormattedDate(datum.key) ?? datum.key,
    }));
  }, [createdVsResolvedData]);

  const periodLabel = selectedCycle
    ? "所选周期"
    : selectedModule
      ? "所选模块"
      : (
          { yesterday: "昨日", last_7_days: "最近7天", last_30_days: "最近30天", last_3_months: "最近90天" } as Record<
            string,
            string
          >
        )[selectedDuration] || "全部时间";
  return (
    <>
      <AnalyticsSectionWrapper title="新增工作项与当前完成情况" subtitle={periodLabel} className="col-span-1">
        {isCreatedVsResolvedLoading ? (
          <ChartLoader />
        ) : parsedData && parsedData.length > 0 ? (
          <TrendChart
            title={`${periodLabel} · ${selectedCycle || selectedModule ? "按创建日期" : "按创建月份"}`}
            data={parsedData.map((row) => ({
              key: String(row.key),
              name: String(row.name),
              created_issues: Number(row.created_issues) || 0,
              completed_issues: Number(row.completed_issues) || 0,
            }))}
            onSelect={(month, series) => setDetail({ month, completed: series === "completed_issues" })}
            series={[
              { key: "created_issues", label: "新增工作项", color: "#4b86c6" },
              { key: "completed_issues", label: "其中已完成", color: "#379b76" },
            ]}
          />
        ) : (
          <EmptyStateCompact
            assetKey="unknown"
            assetClassName="size-20"
            rootClassName="border border-subtle px-5 py-10 md:py-20 md:px-20"
            title={t("workspace_empty_state.analytics_work_items.title")}
          />
        )}
      </AnalyticsSectionWrapper>
      {detail && (
        <AnalyticsDetails
          title={`${detail.month.slice(0, 7)} · ${detail.completed ? "其中已完成" : "新增工作项"}`}
          metric="total_work_items"
          isPeekView={isPeekView}
          filters={{
            ...(selectedProjects?.length ? { project_ids: selectedProjects.join(",") } : {}),
            ...(selectedDuration ? { date_filter: selectedDuration } : {}),
            ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
            ...(selectedModule ? { module_id: selectedModule } : {}),
            ...(selectedCycle || selectedModule
              ? { created_day: detail.month }
              : { created_month: `${detail.month.slice(0, 7)}-01` }),
            ...(detail.completed ? { state_group: "completed" } : {}),
          }}
          onClose={() => setDetail(undefined)}
        />
      )}
    </>
  );
});

export default CreatedVsResolved;
