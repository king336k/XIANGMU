/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useEffect } from "react";
import { observer } from "mobx-react";
import { useParams, useSearchParams } from "next/navigation";
import { profileSummaryFilters } from "./overview/links";
import useSWR from "swr";
// plane imports
import { ISSUE_DISPLAY_FILTERS_BY_PAGE } from "@plane/constants";
import { EIssuesStoreType } from "@plane/types";
// components
import { ProfileIssuesKanBanLayout } from "@/components/issues/issue-layouts/kanban/roots/profile-issues-root";
import { ProfileIssuesListLayout } from "@/components/issues/issue-layouts/list/roots/profile-issues-root";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { WorkspaceLevelWorkItemFiltersHOC } from "@/components/work-item-filters/filters-hoc/workspace-level";
import { WorkItemFiltersRow } from "@/components/work-item-filters/filters-row";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
import { IssuesStoreContext } from "@/hooks/use-issue-layout-store";

type Props = {
  type: "assigned" | "subscribed" | "created";
};

export const ProfileIssuesPage = observer(function ProfileIssuesPage(props: Props) {
  const { type } = props;
  const { workspaceSlug, userId } = useParams();
  const searchParams = useSearchParams();
  const summaryQuery = searchParams.toString();
  // store hooks
  const {
    issues: { setViewId },
    issuesFilter: { issueFilters, fetchFilters, updateFilterExpression },
  } = useIssues(EIssuesStoreType.PROFILE);
  // derived values
  const activeLayout = issueFilters?.displayFilters?.layout || undefined;

  useEffect(() => {
    if (setViewId) setViewId(type);
  }, [type, setViewId]);

  const {
    data: filtersReady,
    error: filtersError,
    isValidating: loadingFilters,
  } = useSWR(
    workspaceSlug && userId
      ? `CURRENT_WORKSPACE_PROFILE_ISSUES_${workspaceSlug}_${userId}_${type}_${summaryQuery}`
      : null,
    async () => {
      if (workspaceSlug && userId) {
        await fetchFilters(workspaceSlug, userId, profileSummaryFilters(new URLSearchParams(summaryQuery)));
        return true;
      }
    },
    { revalidateOnMount: true, revalidateIfStale: false, revalidateOnFocus: false }
  );

  if (filtersError)
    return (
      <div role="alert" className="p-5 text-13 text-secondary">
        工作项筛选加载失败，请刷新重试。
      </div>
    );
  if (!filtersReady || loadingFilters)
    return (
      <div role="status" className="p-5 text-13 text-secondary">
        正在加载工作项…
      </div>
    );

  return (
    <IssuesStoreContext.Provider value={EIssuesStoreType.PROFILE}>
      <WorkspaceLevelWorkItemFiltersHOC
        entityId={userId}
        entityType={EIssuesStoreType.PROFILE}
        filtersToShowByLayout={ISSUE_DISPLAY_FILTERS_BY_PAGE.profile_issues.filters}
        initialWorkItemFilters={issueFilters}
        updateFilters={updateFilterExpression.bind(updateFilterExpression, workspaceSlug, userId)}
        workspaceSlug={workspaceSlug}
      >
        {({ filter: profileWorkItemsFilter }) => (
          <>
            <div className="profile-work-items flex h-full w-full min-w-0 flex-col">
              {profileWorkItemsFilter && <WorkItemFiltersRow filter={profileWorkItemsFilter} />}
              <div className="relative h-full w-full overflow-auto">
                {activeLayout === "list" ? (
                  <ProfileIssuesListLayout />
                ) : activeLayout === "kanban" ? (
                  <ProfileIssuesKanBanLayout />
                ) : null}
              </div>
            </div>
            {/* peek overview */}
            <IssuePeekOverview />
          </>
        )}
      </WorkspaceLevelWorkItemFiltersHOC>
    </IssuesStoreContext.Provider>
  );
});
