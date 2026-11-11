import { useParams } from "next/navigation";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { cn } from "@plane/utils";
// assets
import emptyModule from "@/app/assets/empty-state/module.svg?url";
// components
import { EmptyState } from "@/components/common/empty-state";
import { PageHead } from "@/components/core/page-title";
import { ModuleLayoutRoot } from "@/components/issues/issue-layouts/roots/module-layout-root";
import { ModuleAnalyticsSidebar } from "@/components/modules";
// hooks
import { useModule } from "@/hooks/store/use-module";
import { useProject } from "@/hooks/store/use-project";
import { useAppRouter } from "@/hooks/use-app-router";
import useLocalStorage from "@/hooks/use-local-storage";
import type { Route } from "./+types/page";

function ModuleIssuesPage({ params }: Route.ComponentProps) {
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId, moduleId } = useParams() as typeof params;
  // store hooks
  const { fetchModuleDetails, getModuleById } = useModule();
  const { getProjectById } = useProject();
  // const { issuesFilter } = useIssues(EIssuesStoreType.MODULE);
  // local storage
  const { setValue, storedValue } = useLocalStorage("module_sidebar_collapsed", "false");
  const isSidebarCollapsed = storedValue ? (storedValue === "true" ? true : false) : false;
  // fetching module details
  const { error } = useSWR(`CURRENT_MODULE_DETAILS_${moduleId}`, () =>
    fetchModuleDetails(workspaceSlug, projectId, moduleId)
  );
  // derived values
  const projectModule = getModuleById(moduleId);
  const project = getProjectById(projectId);
  const pageTitle = project?.name && projectModule?.name ? `${project?.name} - ${projectModule?.name}` : undefined;

  const toggleSidebar = () => {
    setValue(`${!isSidebarCollapsed}`);
  };

  // const activeLayout = issuesFilter?.issueFilters?.displayFilters?.layout;
  return (
    <>
      <PageHead title={pageTitle} />
      {error ? (
        <EmptyState
          image={emptyModule}
          title="模块不存在"
          description="该模块不存在或已被删除。"
          primaryButton={{
            text: "查看其他模块",
            onClick: () => router.push(`/${workspaceSlug}/projects/${projectId}/modules`),
          }}
        />
      ) : (
        <div className="relative flex h-full min-h-0 w-full min-w-0 overflow-hidden">
          <div
            className={cn("h-full min-h-0 min-w-0 flex-1 overflow-hidden", !isSidebarCollapsed && "hidden xl:block")}
          >
            <ModuleLayoutRoot />
          </div>
          {!isSidebarCollapsed && (
            <aside
              aria-label="模块详情与统计"
              className={cn(
                "vertical-scrollbar flex scrollbar-sm h-full min-h-0 w-full min-w-0 shrink-0 flex-col gap-3.5 overflow-y-auto overscroll-contain border-l border-subtle bg-surface-1 px-4 pb-6 xl:w-[24rem] xl:px-6"
              )}
            >
              <ModuleAnalyticsSidebar moduleId={moduleId} handleClose={toggleSidebar} />
            </aside>
          )}
        </div>
      )}
    </>
  );
}

export default observer(ModuleIssuesPage);
