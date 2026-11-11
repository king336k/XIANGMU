/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef, useState, useEffect } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { useTranslation } from "@plane/i18n";
// plane types
import { PageIcon, ProjectIcon, WorkItemsIcon } from "@plane/propel/icons";
import type { TActivityEntityData, THomeWidgetProps, TRecentActivityFilterKeys } from "@plane/types";
// plane ui
// components
import { Paging } from "@/components/quality/shared";
import { errorMessage } from "@/components/quality/api";
// plane web services
import { WorkspaceService } from "@/services/workspace.service";
import { RecentsEmptyState } from "../empty-states";
import { EWidgetKeys, WidgetLoader } from "../loaders";
import { FiltersDropdown } from "./filters";
import { RecentIssue } from "./issue";
import { RecentPage } from "./page";
import { RecentProject } from "./project";

const WIDGET_KEY = EWidgetKeys.RECENT_ACTIVITY;
const workspaceService = new WorkspaceService();
const filters: { name: TRecentActivityFilterKeys; icon?: React.ReactNode; i18n_key: string }[] = [
  { name: "all item", i18n_key: "home.recents.filters.all" },
  { name: "issue", icon: <WorkItemsIcon className="h-4 w-4" />, i18n_key: "home.recents.filters.issues" },
  { name: "page", icon: <PageIcon height={16} width={16} />, i18n_key: "home.recents.filters.pages" },
  { name: "project", icon: <ProjectIcon height={16} width={16} />, i18n_key: "home.recents.filters.projects" },
];

type TRecentWidgetProps = THomeWidgetProps & {
  presetFilter?: TRecentActivityFilterKeys;
  showFilterSelect?: boolean;
};

export const RecentActivityWidget = observer(function RecentActivityWidget(props: TRecentWidgetProps) {
  const { presetFilter, showFilterSelect = true, workspaceSlug } = props;
  // states
  const [filter, setFilter] = useState<TRecentActivityFilterKeys>(presetFilter ?? filters[0].name);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  useEffect(() => setPage(1), [workspaceSlug, filter, perPage]);
  const { t } = useTranslation();
  // ref
  const ref = useRef<HTMLDivElement>(null);

  const { data, isLoading, error } = useSWR(
    workspaceSlug ? `WORKSPACE_RECENT_ACTIVITY_${workspaceSlug}_${filter}_${page}_${perPage}` : null,
    workspaceSlug
      ? () =>
          workspaceService.fetchWorkspaceRecentPage(
            workspaceSlug.toString(),
            filter === filters[0].name ? undefined : filter,
            page,
            perPage
          )
      : null,
    {
      revalidateIfStale: false,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
    }
  );

  useEffect(() => {
    if (data) {
      const lastPage = Math.max(1, Math.ceil(data.count / perPage));
      if (page > lastPage) setPage(lastPage);
    }
  }, [data, page, perPage]);

  const resolveRecent = (activity: TActivityEntityData) => {
    switch (activity.entity_name) {
      case "page":
      case "workspace_page":
        return <RecentPage activity={activity} ref={ref} workspaceSlug={workspaceSlug} />;
      case "project":
        return <RecentProject activity={activity} ref={ref} workspaceSlug={workspaceSlug} />;
      case "issue":
        return <RecentIssue activity={activity} ref={ref} workspaceSlug={workspaceSlug} />;
      default:
        return <></>;
    }
  };

  if (!isLoading && data?.count === 0)
    return (
      <div ref={ref} className="max-h-[500px] overflow-y-scroll">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-14 font-semibold text-tertiary">{t("home.recents.title")}</div>
          {showFilterSelect && <FiltersDropdown filters={filters} activeFilter={filter} setActiveFilter={setFilter} />}
        </div>
        <div className="flex flex-col items-center justify-center">
          <RecentsEmptyState type={filter} />
        </div>
      </div>
    );

  return (
    <section ref={ref} className="@container min-w-0 space-y-2" aria-label="最近访问">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-14 font-semibold text-tertiary">{t("home.recents.title")}</div>
        {showFilterSelect && <FiltersDropdown filters={filters} activeFilter={filter} setActiveFilter={setFilter} />}
      </div>
      <div className="grid min-h-[160px] grid-cols-1 content-start @5xl:grid-cols-2">
        {isLoading && <WidgetLoader widgetKey={WIDGET_KEY} />}
        {!isLoading &&
          data?.results
            ?.filter((recent) => recent.entity_data)
            .map((activity) => <div key={activity.id}>{resolveRecent(activity)}</div>)}
      </div>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {data && data.count > 0 && (
        <Paging
          pageSizes={[10, 20, 50]}
          page={page}
          count={data.count}
          perPage={perPage}
          onChange={setPage}
          onPageSizeChange={(size) => {
            setPage(1);
            setPerPage(size);
          }}
        />
      )}
    </section>
  );
});
