/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useUserPermissions } from "@/hooks/store/user";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";

// components
import { Outlet } from "react-router";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { ProjectsListMobileHeader } from "@/components/projects/mobile-header";
import { ProjectsBaseHeader } from "@/components/project/header";

function ProjectListLayout() {
  const { workspaceSlug } = useParams();
  const { allowPermissions } = useUserPermissions();
  if (
    !allowPermissions(
      [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
      EUserPermissionsLevel.WORKSPACE,
      workspaceSlug?.toString() || ""
    )
  )
    return <NotAuthorizedView />;
  return (
    <>
      <AppHeader header={<ProjectsBaseHeader />} mobileHeader={<ProjectsListMobileHeader />} />
      <ContentWrapper>
        <Outlet />
      </ContentWrapper>
    </>
  );
}

export default observer(ProjectListLayout);
