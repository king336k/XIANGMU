import { useParams } from "next/navigation";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// components
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { EstimateRoot } from "@/components/estimates";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useSettingsPermissions } from "@/components/settings/use-settings-permissions";
// local imports
import type { Route } from "./+types/page";
import { EstimatesProjectSettingsHeader } from "./header";

function EstimatesSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = useParams() as typeof params;
  // store
  const { currentProjectDetails } = useProject();
  const { workspaceUserInfo, allowPermissions } = useSettingsPermissions();

  // derived values
  const pageTitle = currentProjectDetails?.name ? `${currentProjectDetails?.name} - 估点` : undefined;
  const canPerformProjectAdminActions = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);

  if (workspaceUserInfo && !canPerformProjectAdminActions) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<EstimatesProjectSettingsHeader />}>
      <PageHead title={pageTitle} />
      <div className={`w-full ${canPerformProjectAdminActions ? "" : "pointer-events-none opacity-60"}`}>
        <EstimateRoot workspaceSlug={workspaceSlug} projectId={projectId} isAdmin={canPerformProjectAdminActions} />
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(EstimatesSettingsPage);
