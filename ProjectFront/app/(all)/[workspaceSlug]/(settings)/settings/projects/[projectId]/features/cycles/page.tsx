import { useParams } from "next/navigation";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
// components
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { ProjectSettingsFeatureControlItem } from "@/components/settings/project/content/feature-control-item";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useSettingsPermissions } from "@/components/settings/use-settings-permissions";
// local imports
import type { Route } from "./+types/page";
import { FeaturesCyclesProjectSettingsHeader } from "./header";
import { SettingsHeading } from "@/components/settings/heading";

function FeaturesCyclesSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = useParams() as typeof params;
  // store hooks
  const { workspaceUserInfo, allowPermissions } = useSettingsPermissions();
  const { currentProjectDetails } = useProject();
  // translation
  const { t } = useTranslation();
  // derived values
  const pageTitle = currentProjectDetails?.name
    ? `${currentProjectDetails?.name} 设置 - ${t("project_settings.features.cycles.short_title")}`
    : undefined;
  const canPerformProjectAdminActions = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);

  if (workspaceUserInfo && !canPerformProjectAdminActions) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<FeaturesCyclesProjectSettingsHeader />}>
      <PageHead title={pageTitle} />
      <section className="w-full">
        <SettingsHeading
          title={t("project_settings.features.cycles.title")}
          description={t("project_settings.features.cycles.description")}
        />
        <div className="mt-7">
          <ProjectSettingsFeatureControlItem
            title={t("project_settings.features.cycles.toggle_title")}
            description={t("project_settings.features.cycles.toggle_description")}
            featureProperty="cycle_view"
            projectId={projectId}
            value={!!currentProjectDetails?.cycle_view}
            workspaceSlug={workspaceSlug}
          />
        </div>
      </section>
    </SettingsContentWrapper>
  );
}

export default observer(FeaturesCyclesSettingsPage);
