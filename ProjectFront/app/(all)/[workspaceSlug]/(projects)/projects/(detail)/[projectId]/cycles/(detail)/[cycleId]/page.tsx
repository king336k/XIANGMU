import { useParams } from "next/navigation";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { cn } from "@plane/utils";
// assets
import emptyCycle from "@/app/assets/empty-state/cycle.svg?url";
// components
import { EmptyState } from "@/components/common/empty-state";
import { PageHead } from "@/components/core/page-title";
import useCyclesDetails from "@/components/cycles/active-cycle/use-cycles-details";
import { CycleDetailsSidebar } from "@/components/cycles/analytics-sidebar";
import { CycleLayoutRoot } from "@/components/issues/issue-layouts/roots/cycle-layout-root";
// hooks
import { useCycle } from "@/hooks/store/use-cycle";
import { useProject } from "@/hooks/store/use-project";
import { useAppRouter } from "@/hooks/use-app-router";
import useLocalStorage from "@/hooks/use-local-storage";
import type { Route } from "./+types/page";

function CycleDetailPage({ params }: Route.ComponentProps) {
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId, cycleId } = useParams() as typeof params;
  // store hooks
  const { getCycleById, loader } = useCycle();
  const { getProjectById } = useProject();
  // const { issuesFilter } = useIssues(EIssuesStoreType.CYCLE);
  // hooks
  const { setValue, storedValue } = useLocalStorage("cycle_sidebar_collapsed", false);

  useCyclesDetails({
    workspaceSlug,
    projectId,
    cycleId,
  });
  // derived values
  const isSidebarCollapsed = storedValue ? (storedValue === true ? true : false) : false;
  const cycle = getCycleById(cycleId);
  const project = getProjectById(projectId);
  const pageTitle = project?.name && cycle?.name ? `${project?.name} - ${cycle?.name}` : undefined;

  /**
   * Toggles the sidebar
   */
  const toggleSidebar = () => setValue(!isSidebarCollapsed);

  // const activeLayout = issuesFilter?.issueFilters?.displayFilters?.layout;
  return (
    <>
      <PageHead title={pageTitle} />
      {!cycle && !loader ? (
        <EmptyState
          image={emptyCycle}
          title="周期不存在"
          description="该周期不存在或已被删除。"
          primaryButton={{
            text: "查看其他周期",
            onClick: () => router.push(`/${workspaceSlug}/projects/${projectId}/cycles`),
          }}
        />
      ) : (
        <>
          <div className="relative flex h-full min-h-0 w-full min-w-0 overflow-hidden">
            <div
              className={cn("h-full min-h-0 min-w-0 flex-1 overflow-hidden", !isSidebarCollapsed && "hidden xl:block")}
            >
              <CycleLayoutRoot />
            </div>
            {!isSidebarCollapsed && (
              <aside
                aria-label="周期详情与统计"
                className={cn(
                  "vertical-scrollbar flex scrollbar-sm h-full min-h-0 w-full min-w-0 shrink-0 flex-col gap-3.5 overflow-y-auto overscroll-contain border-l border-subtle bg-surface-1 px-4 pb-6 xl:w-[21.5rem]"
                )}
              >
                <CycleDetailsSidebar
                  handleClose={toggleSidebar}
                  cycleId={cycleId}
                  projectId={projectId}
                  workspaceSlug={workspaceSlug}
                />
              </aside>
            )}
          </div>
        </>
      )}
    </>
  );
}

export default observer(CycleDetailPage);
