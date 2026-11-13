// SPDX-License-Identifier: AGPL-3.0-only
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { useAnalytics } from "@/hooks/store/use-analytics";
import { OwnerSummary } from "@/components/quality/owner-summary";
import { analyticsOwnerMetrics } from "@/components/quality/owner-metrics";
export const AnalyticsOwnerSummary = observer(function AnalyticsOwnerSummary() {
  const { workspaceSlug } = useParams();
  const { selectedProjects, selectedCycle, selectedModule, isEpic, isPeekView } = useAnalytics();
  const params = new URLSearchParams({
    ...(selectedProjects?.length ? { project_ids: selectedProjects.join(",") } : {}),
    ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
    ...(selectedModule ? { module_id: selectedModule } : {}),
    ...(isEpic ? { epic: "true" } : {}),
  });
  const metrics =
    selectedCycle || selectedModule || isEpic
      ? analyticsOwnerMetrics.filter(
          (item) =>
            !["total_defects", "total_test_plans", "total_test_executions", "total_manual_executions"].includes(
              item.key
            )
        )
      : analyticsOwnerMetrics;
  const project = isPeekView ? selectedProjects?.[0] : undefined;
  const endpoint = `/api/workspaces/${workspaceSlug}${project ? `/projects/${project}/quality` : ""}/owner-statistics/`;
  return (
    <div className="space-y-2">
      <p className="text-12 text-secondary">人员事项 · 累计全部时间</p>
      <OwnerSummary
        key={`${endpoint}:${params}`}
        endpoint={endpoint}
        source="analytics"
        params={params}
        metrics={metrics}
      />
    </div>
  );
});
