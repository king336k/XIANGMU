/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useSearchParams } from "react-router";
import { ownerStatisticsScope } from "@/components/quality/owner-statistics";
import { OwnerSummary } from "@/components/quality/owner-summary";
import { observer } from "mobx-react";
import { Tab } from "@headlessui/react";
import { useTranslation } from "@plane/i18n";
import type { TWorkItemFilterCondition } from "@plane/shared-state";
import type { TModuleDistribution, TModuleEstimateDistribution, TModulePlotType } from "@plane/types";
import { cn, toFilterArray } from "@plane/utils";
// components
import type { TAssigneeData } from "@/components/core/sidebar/progress-stats/assignee";
import { AssigneeStatComponent } from "@/components/core/sidebar/progress-stats/assignee";
import type { TLabelData } from "@/components/core/sidebar/progress-stats/label";
import { LabelStatComponent } from "@/components/core/sidebar/progress-stats/label";
import type { TSelectedFilterProgressStats } from "@/components/core/sidebar/progress-stats/shared";
import { createFilterUpdateHandler, PROGRESS_STATS } from "@/components/core/sidebar/progress-stats/shared";
import type { TStateGroupData } from "@/components/core/sidebar/progress-stats/state_group";
import { StateGroupStatComponent } from "@/components/core/sidebar/progress-stats/state_group";
// hooks
import useLocalStorage from "@/hooks/use-local-storage";

type TModuleProgressStats = {
  distribution: TModuleDistribution | TModuleEstimateDistribution | undefined;
  groupedIssues: Record<string, number>;
  handleFiltersUpdate: (condition: TWorkItemFilterCondition) => void;
  isEditable?: boolean;
  ownerEndpoint?: string;
  ownerParams?: URLSearchParams;
  historical?: boolean;
  moduleId: string;
  noBackground?: boolean;
  plotType: TModulePlotType;
  roundedTab?: boolean;
  selectedFilters: TSelectedFilterProgressStats;
  size?: "xs" | "sm";
  totalIssuesCount: number;
};

export const ModuleProgressStats = observer(function ModuleProgressStats(props: TModuleProgressStats) {
  const {
    distribution,
    groupedIssues,
    handleFiltersUpdate,
    isEditable = false,
    ownerEndpoint,
    ownerParams,
    historical = false,
    moduleId,
    noBackground = false,
    plotType,
    roundedTab = false,
    selectedFilters,
    size = "sm",
    totalIssuesCount,
  } = props;
  // plane imports
  const [ownerRoute, setOwnerRoute] = useSearchParams();
  const { t } = useTranslation();
  // hooks
  const { storedValue: currentTab, setValue: setModuleTab } = useLocalStorage(
    `module-analytics-tab-${moduleId}`,
    "stat-assignees"
  );
  // derived values
  const currentTabIndex = (tab: string): number => PROGRESS_STATS.findIndex((stat) => stat.key === tab);
  const currentDistribution = distribution as TModuleDistribution;
  const currentEstimateDistribution = distribution as TModuleEstimateDistribution;
  const selectedAssigneeIds = toFilterArray(selectedFilters?.assignees?.value || []) as string[];
  const selectedLabelIds = toFilterArray(selectedFilters?.labels?.value || []) as string[];
  const selectedStateGroups = toFilterArray(selectedFilters?.stateGroups?.value || []) as string[];

  const distributionAssigneeData: TAssigneeData =
    plotType === "burndown"
      ? (currentDistribution?.assignees || []).map((assignee) => ({
          id: assignee?.assignee_id || undefined,
          title: assignee?.display_name || undefined,
          avatar_url: assignee?.avatar_url || undefined,
          completed: assignee.completed_issues,
          total: assignee.total_issues,
        }))
      : (currentEstimateDistribution?.assignees || []).map((assignee) => ({
          id: assignee?.assignee_id || undefined,
          title: assignee?.display_name || undefined,
          avatar_url: assignee?.avatar_url || undefined,
          completed: assignee.completed_estimates,
          total: assignee.total_estimates,
        }));

  const distributionLabelData: TLabelData =
    plotType === "burndown"
      ? (currentDistribution?.labels || []).map((label) => ({
          id: label?.label_id || undefined,
          title: label?.label_name || undefined,
          color: label?.color || undefined,
          completed: label.completed_issues,
          total: label.total_issues,
        }))
      : (currentEstimateDistribution?.labels || []).map((label) => ({
          id: label?.label_id || undefined,
          title: label?.label_name || undefined,
          color: label?.color || undefined,
          completed: label.completed_estimates,
          total: label.total_estimates,
        }));

  const distributionStateData: TStateGroupData = Object.keys(groupedIssues || {}).map((state) => ({
    state: state,
    completed: groupedIssues?.[state] || 0,
    total: totalIssuesCount || 0,
  }));

  const handleAssigneeFiltersUpdate = createFilterUpdateHandler(
    "assignee_id",
    selectedAssigneeIds,
    handleFiltersUpdate
  );
  const handleLabelFiltersUpdate = createFilterUpdateHandler("label_id", selectedLabelIds, handleFiltersUpdate);
  const handleStateGroupFiltersUpdate = createFilterUpdateHandler(
    "state_group",
    selectedStateGroups,
    handleFiltersUpdate
  );

  return (
    <div>
      <Tab.Group defaultIndex={currentTabIndex(currentTab ? currentTab : "stat-assignees")}>
        <Tab.List
          as="div"
          className={cn(
            `flex w-full items-center justify-between gap-2 rounded-md p-1`,
            roundedTab ? `rounded-3xl` : `rounded-md`,
            noBackground ? `` : `bg-layer-2`,
            size === "xs" ? `text-11` : `text-13`
          )}
        >
          {PROGRESS_STATS.map((stat) => (
            <Tab
              className={cn(
                `w-full cursor-pointer p-1 text-primary transition-all outline-none focus:outline-none`,
                roundedTab ? `rounded-3xl border border-subtle` : `rounded-sm`,
                stat.key === currentTab
                  ? "bg-layer-transparent-active text-secondary"
                  : "text-placeholder hover:text-secondary"
              )}
              key={stat.key}
              onClick={() => setModuleTab(stat.key)}
            >
              {t(stat.i18n_title)}
            </Tab>
          ))}
        </Tab.List>
        <Tab.Panels className="py-3 text-secondary">
          <Tab.Panel key={"stat-assignees"}>
            <AssigneeStatComponent
              distribution={distributionAssigneeData}
              canView={!historical}
              unit={plotType === "points" ? "点" : "条"}
              onOpenAssignee={
                ownerEndpoint
                  ? (id, name) => {
                      const next = new URLSearchParams(ownerRoute);
                      next.set(
                        "owner_scope",
                        ownerStatisticsScope(ownerEndpoint, "work_items", ownerParams || new URLSearchParams())
                      );
                      next.set("owner_id", id);
                      next.set("owner_name", name);
                      next.set("owner_metric", "total_work_items");
                      next.delete("owner_status");
                      next.set("owner_detail_page", "1");
                      setOwnerRoute(next, { replace: true, preventScrollReset: true });
                    }
                  : undefined
              }
              handleAssigneeFiltersUpdate={handleAssigneeFiltersUpdate}
              isEditable={isEditable}
              selectedAssigneeIds={selectedAssigneeIds}
            />
          </Tab.Panel>
          <Tab.Panel key={"stat-labels"}>
            <LabelStatComponent
              distribution={distributionLabelData}
              handleLabelFiltersUpdate={handleLabelFiltersUpdate}
              isEditable={isEditable}
              selectedLabelIds={selectedLabelIds}
            />
          </Tab.Panel>
          <Tab.Panel key={"stat-states"}>
            <StateGroupStatComponent
              distribution={distributionStateData}
              handleStateGroupFiltersUpdate={handleStateGroupFiltersUpdate}
              isEditable={isEditable}
              selectedStateGroups={selectedStateGroups}
              totalIssuesCount={totalIssuesCount}
            />
          </Tab.Panel>
        </Tab.Panels>
      </Tab.Group>
      {plotType === "points" && !historical && (
        <p className="mt-2 text-11 text-secondary">估算点 · 点击查看对应任务与需求</p>
      )}
      {historical && <p className="mt-2 text-11 text-secondary">完成时快照</p>}
      {ownerEndpoint && ownerParams && !historical && (
        <OwnerSummary
          endpoint={ownerEndpoint}
          source="work_items"
          params={ownerParams}
          metrics={[{ key: "total_work_items", label: plotType === "points" ? "对应任务与需求" : "任务与需求" }]}
          detailsOnly
        />
      )}
    </div>
  );
});
