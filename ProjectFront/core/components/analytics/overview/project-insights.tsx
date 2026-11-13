/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { StatisticsDisplay } from "@/components/quality/statistics-display";
import type { StatisticsMode } from "@/components/quality/statistics-display";
import { observer } from "mobx-react";
import { AnalyticsDetails } from "../analytics-details";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane package imports
import { useTranslation } from "@plane/i18n";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import type { TChartData } from "@plane/types";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
// services
import { AnalyticsService } from "@/services/analytics.service";
// plane web components
import AnalyticsSectionWrapper from "../analytics-section-wrapper";
import { ProjectInsightsLoader } from "../loaders";

const analyticsService = new AnalyticsService();

const ProjectInsights = observer(function ProjectInsights() {
  const params = useParams();
  const { t } = useTranslation();
  const [mode, setMode] = useState<StatisticsMode>("bar");
  const workspaceSlug = params.workspaceSlug.toString();
  const [detail, setDetail] = useState<{ metric: string; title: string }>();
  const labels: Record<string, string> = {
    work_items: "工作项",
    cycles: "周期",
    modules: "模块",
    intake: "待评估事项",
    members: "成员",
    pages: "项目文档",
    views: "项目视图",
  };
  const { selectedDuration, selectedProjects, selectedCycle, selectedModule, isPeekView } = useAnalytics();

  const { data: projectInsightsData, isLoading: isLoadingProjectInsight } = useSWR(
    `radar-chart-project-insights-${workspaceSlug}-${selectedDuration}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<TChartData<string, string>[]>(
        workspaceSlug,
        "projects",
        {
          // date_filter: selectedDuration,
          ...(selectedProjects?.length > 0 && { project_ids: selectedProjects?.join(",") }),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
        },
        isPeekView
      )
  );
  const localizedData = projectInsightsData?.map((item) => ({
    key: String(item.key),
    name: labels[String(item.key)] || String(item.name),
    count: Number(item.count),
  }));
  const openSection = (key: string) => {
    setDetail({ metric: key === "members" ? "total_users" : `total_${key}`, title: labels[key] || key });
  };
  const filters: Record<string, string> = {
    ...(selectedProjects?.length ? { project_ids: selectedProjects.join(",") } : {}),
    ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
    ...(selectedModule ? { module_id: selectedModule } : {}),
  };

  return (
    <>
      <AnalyticsSectionWrapper
        title={`${t("workspace_analytics.project_insights")}`}
        subtitle="全部时间"
        className="md:col-span-3"
      >
        {isLoadingProjectInsight ? (
          <ProjectInsightsLoader />
        ) : projectInsightsData && projectInsightsData?.length == 0 ? (
          <EmptyStateCompact
            assetKey="unknown"
            assetClassName="size-20"
            rootClassName="border border-subtle px-5 py-10 md:py-20 md:px-20"
            title={t("workspace_empty_state.analytics_work_items.title")}
          />
        ) : (
          <div className="space-y-4 rounded-md border border-subtle p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-12 text-secondary">
                {selectedProjects?.length ? "所选项目资源数量" : "可见项目资源数量"}
              </span>
              <StatisticsDisplay value={mode} onChange={setMode} options={["bar", "table"]} />
            </div>
            {mode === "table" ? (
              <table className="w-full text-left text-12">
                <thead className="text-secondary">
                  <tr>
                    <th className="py-2">资源</th>
                    <th className="text-right">数量</th>
                  </tr>
                </thead>
                <tbody>
                  {localizedData?.map((row) => (
                    <tr key={row.key} className="border-t border-subtle">
                      <td className="py-2">
                        <button type="button" onClick={() => openSection(row.key)} className="text-accent-primary">
                          {row.name}
                        </button>
                      </td>
                      <td className="text-right tabular-nums">
                        <button type="button" onClick={() => openSection(row.key)} className="text-accent-primary">
                          {row.count}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="space-y-4">
                {localizedData?.map((row) => (
                  <button
                    key={row.key}
                    type="button"
                    onClick={() => openSection(row.key)}
                    className="block w-full text-left"
                  >
                    <span className="mb-2 flex justify-between text-12">
                      <span>{row.name}</span>
                      <strong className="tabular-nums">{row.count}</strong>
                    </span>
                    <span className="block h-2 overflow-hidden rounded bg-layer-1">
                      <span
                        className="block h-full rounded bg-accent-primary/70"
                        style={{
                          width: `${(row.count / Math.max(1, ...(localizedData || []).map((item) => item.count))) * 100}%`,
                        }}
                      />
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </AnalyticsSectionWrapper>
      {detail && (
        <AnalyticsDetails
          title={detail.title}
          metric={detail.metric}
          filters={filters}
          isPeekView={isPeekView}
          onClose={() => setDetail(undefined)}
        />
      )}
    </>
  );
});

export default ProjectInsights;
