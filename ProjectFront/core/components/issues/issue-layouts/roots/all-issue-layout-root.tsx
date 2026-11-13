/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { OwnerSummary } from "@/components/quality/owner-summary";
import React, { useCallback, useMemo } from "react";
import { observer } from "mobx-react";
import { useParams, useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { GLOBAL_VIEW_TRACKER_ELEMENTS, ISSUE_DISPLAY_FILTERS_BY_PAGE } from "@plane/constants";
import { EmptyStateDetailed } from "@plane/propel/empty-state";
import type { EIssueLayoutTypes } from "@plane/types";
import { EIssuesStoreType, STATIC_VIEW_TYPES } from "@plane/types";
// assets
// components
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { WorkspaceActiveLayout } from "@/components/views/helper";
import { WorkspaceLevelWorkItemFiltersHOC } from "@/components/work-item-filters/filters-hoc/workspace-level";
import { WorkItemFiltersRow } from "@/components/work-item-filters/filters-row";
// hooks
import { useGlobalView } from "@/hooks/store/use-global-view";
import { useIssues } from "@/hooks/store/use-issues";
import { useAppRouter } from "@/hooks/use-app-router";
import { IssuesStoreContext } from "@/hooks/use-issue-layout-store";
import { useWorkspaceIssueProperties } from "@/hooks/use-workspace-issue-properties";

type Props = {
  isDefaultView: boolean;
  isLoading?: boolean;
  toggleLoading: (value: boolean) => void;
};

export const AllIssueLayoutRoot = observer(function AllIssueLayoutRoot(props: Props) {
  const { isDefaultView, isLoading = false, toggleLoading } = props;
  // router
  const router = useAppRouter();
  const { workspaceSlug: routerWorkspaceSlug, globalViewId: routerGlobalViewId } = useParams();
  const workspaceSlug = routerWorkspaceSlug ? routerWorkspaceSlug.toString() : undefined;
  const globalViewId = routerGlobalViewId ? routerGlobalViewId.toString() : undefined;
  // search params
  const searchParams = useSearchParams();
  // store hooks
  const {
    issuesFilter: { filters, fetchFilters, updateFilterExpression, getFilterParams },
    issues: { clear, groupedIssueIds, fetchIssues, fetchNextIssues },
  } = useIssues(EIssuesStoreType.GLOBAL);
  const { fetchAllGlobalViews, getViewDetailsById } = useGlobalView();
  // Derived values
  const viewDetails = globalViewId ? getViewDetailsById(globalViewId) : undefined;
  const workItemFilters = globalViewId ? filters?.[globalViewId] : undefined;
  const activeLayout: EIssueLayoutTypes | undefined = workItemFilters?.displayFilters?.layout;
  // Determine initial work item filters based on view type and availability
  const initialWorkItemFilters = useMemo(() => {
    if (!globalViewId) return undefined;

    const isStaticView = STATIC_VIEW_TYPES.includes(globalViewId);
    const hasViewDetails = Boolean(viewDetails);

    if (!isStaticView && !hasViewDetails) return undefined;

    return {
      displayFilters: workItemFilters?.displayFilters,
      displayProperties: workItemFilters?.displayProperties,
      kanbanFilters: workItemFilters?.kanbanFilters,
      richFilters: viewDetails?.rich_filters ?? {},
    };
  }, [globalViewId, viewDetails, workItemFilters]);

  // Custom hooks
  useWorkspaceIssueProperties(workspaceSlug);

  // Route filters
  const routeFilters: { [key: string]: string } = {};
  searchParams.forEach((value: string, key: string) => {
    routeFilters[key] = value;
  });

  // Fetch next pages callback
  const fetchNextPages = useCallback(() => {
    if (workspaceSlug && globalViewId) fetchNextIssues(workspaceSlug, globalViewId);
  }, [fetchNextIssues, workspaceSlug, globalViewId]);

  // Fetch global views
  const { isLoading: globalViewsLoading } = useSWR(
    workspaceSlug ? `WORKSPACE_GLOBAL_VIEWS_${workspaceSlug}` : null,
    async () => {
      if (workspaceSlug) {
        await fetchAllGlobalViews(workspaceSlug);
      }
    },
    { revalidateIfStale: false, revalidateOnFocus: false }
  );

  // Fetch issues
  const { isLoading: issuesLoading } = useSWR(
    workspaceSlug && globalViewId ? `WORKSPACE_GLOBAL_VIEW_ISSUES_${workspaceSlug}_${globalViewId}` : null,
    async () => {
      if (workspaceSlug && globalViewId) {
        clear();
        toggleLoading(true);
        await fetchFilters(workspaceSlug, globalViewId);
        await fetchIssues(workspaceSlug, globalViewId, groupedIssueIds ? "mutation" : "init-loader", {
          canGroup: false,
          perPageCount: 100,
        });
        toggleLoading(false);
      }
    },
    { revalidateIfStale: false, revalidateOnFocus: false }
  );

  // Empty state
  if (!isLoading && !globalViewsLoading && !issuesLoading && !viewDetails && !isDefaultView) {
    return (
      <EmptyStateDetailed
        title="视图不存在"
        description="该视图不存在或你没有访问权限。"
        assetKey="view"
        actions={[
          {
            label: "前往所有工作项",
            onClick: () => router.push(`/${workspaceSlug}/workspace-views/all-issues`),
            variant: "primary",
          },
        ]}
      />
    );
  }

  if (!workspaceSlug || !globalViewId) return null;
  return (
    <IssuesStoreContext.Provider value={EIssuesStoreType.GLOBAL}>
      <WorkspaceLevelWorkItemFiltersHOC
        enableSaveView
        saveViewOptions={{
          label: "另存为",
        }}
        enableUpdateView
        entityId={globalViewId}
        entityType={EIssuesStoreType.GLOBAL}
        filtersToShowByLayout={ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.filters}
        initialWorkItemFilters={initialWorkItemFilters}
        updateFilters={updateFilterExpression.bind(updateFilterExpression, workspaceSlug, globalViewId)}
        workspaceSlug={workspaceSlug}
      >
        {({ filter: globalWorkItemsFilter }) => (
          <div className="h-full overflow-hidden bg-surface-1">
            <div className="flex h-full w-full flex-col border-b border-strong">
              {globalWorkItemsFilter && (
                <WorkItemFiltersRow
                  filter={globalWorkItemsFilter}
                  trackerElements={{
                    saveView: GLOBAL_VIEW_TRACKER_ELEMENTS.HEADER_SAVE_VIEW_BUTTON,
                  }}
                />
              )}
              {!globalViewsLoading && !issuesLoading && (
                <details className="mx-4 my-2 shrink-0 rounded-md border border-subtle p-3">
                  <summary className="cursor-pointer text-13">人员事项</summary>
                  <div className="mt-3 max-h-80 overflow-auto">
                    <OwnerSummary
                      endpoint={`/api/workspaces/${workspaceSlug}/owner-statistics/`}
                      source="work_items"
                      params={
                        new URLSearchParams(
                          Object.fromEntries(
                            Object.entries({
                              ...getFilterParams(
                                { canGroup: false, perPageCount: 100 },
                                globalViewId,
                                undefined,
                                undefined,
                                undefined
                              ),
                              ...routeFilters,
                            }).map(([key, value]) => [key, String(value)])
                          )
                        )
                      }
                      metrics={[{ key: "total_work_items", label: "当前任务与需求" }]}
                    />
                  </div>
                </details>
              )}
              <WorkspaceActiveLayout
                activeLayout={activeLayout}
                isDefaultView={isDefaultView}
                isLoading={isLoading}
                toggleLoading={toggleLoading}
                workspaceSlug={workspaceSlug}
                globalViewId={globalViewId}
                routeFilters={routeFilters}
                fetchNextPages={fetchNextPages}
                globalViewsLoading={globalViewsLoading}
                issuesLoading={issuesLoading}
              />
            </div>
            {/* peek overview */}
            <IssuePeekOverview />
          </div>
        )}
      </WorkspaceLevelWorkItemFiltersHOC>
    </IssuesStoreContext.Provider>
  );
});
