/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { ContentWrapper } from "@plane/ui";
// hooks
import { useHome } from "@/hooks/store/use-home";
// local imports
import { PersonalTodos } from "./personal-todos";
import { DashboardWidgets } from "./home-dashboard-widgets";
import { HomePeekOverviewsRoot } from "../issues/peek-overview/peek-overviews";

export const WorkspaceHomeView = observer(function WorkspaceHomeView() {
  // store hooks
  const { workspaceSlug } = useParams();
  const { fetchWidgets } = useHome();

  useSWR(
    workspaceSlug ? `HOME_DASHBOARD_WIDGETS_${workspaceSlug}` : null,
    workspaceSlug ? () => fetchWidgets(workspaceSlug?.toString()) : null,
    {
      revalidateIfStale: true,
      revalidateOnFocus: false,
      revalidateOnReconnect: true,
    }
  );

  // TODO: refactor loader implementation
  return (
    <>
      <>
        <HomePeekOverviewsRoot />
        <ContentWrapper className="platform-content @container scrollbar-hide w-full gap-5 bg-surface-1 px-4 pb-6 sm:px-6 xl:px-8">
          <div className="w-full min-w-0 space-y-5 pt-4">
            {workspaceSlug && <PersonalTodos workspaceSlug={workspaceSlug.toString()} />}
            <DashboardWidgets />
          </div>
        </ContentWrapper>
      </>
    </>
  );
});
