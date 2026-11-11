/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { qualityApi } from "@/components/quality/api";
import { useNativeWorkAccess } from "@/hooks/use-native-work-access";
// plane imports
import { EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { EmptyStateDetailed } from "@plane/propel/empty-state";
import { EIssuesStoreType, EUserWorkspaceRoles } from "@plane/types";
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";

export const GlobalViewEmptyState = observer(function GlobalViewEmptyState() {
  // plane imports
  const { t } = useTranslation();
  // store hooks
  const { workspaceProjectIds } = useProject();
  const { toggleCreateIssueModal, toggleCreateProjectModal } = useCommandPalette();
  const { allowPermissions } = useUserPermissions();
  const { canArrangeWork } = useNativeWorkAccess();
  const { data: account } = useSWR("/api/quality-auth/account-security/", (url: string) =>
    qualityApi.read<{ can_create_workspace: boolean }>(url)
  );
  // derived values
  const hasMemberLevelPermission = allowPermissions(
    [EUserWorkspaceRoles.ADMIN, EUserWorkspaceRoles.MEMBER],
    EUserPermissionsLevel.WORKSPACE
  );

  if (workspaceProjectIds?.length === 0) {
    return (
      <EmptyStateDetailed
        title={t("workspace_projects.empty_state.no_projects.title")}
        description={t("workspace_projects.empty_state.no_projects.description")}
        assetKey="project"
        assetClassName="size-40"
        actions={[
          {
            label: t("workspace_projects.empty_state.no_projects.primary_button.text"),
            onClick: () => {
              toggleCreateProjectModal(true);
            },
            disabled: !hasMemberLevelPermission || account?.can_create_workspace !== true,
            variant: "primary",
          },
        ]}
      />
    );
  }

  return (
    <EmptyStateDetailed
      title={t(`workspace_empty_state.views.title`)}
      assetKey="project"
      assetClassName="size-40"
      actions={[
        {
          label: t(`workspace_empty_state.views.cta_primary`),
          onClick: () => {
            toggleCreateIssueModal(true, EIssuesStoreType.PROJECT);
          },
          disabled: !hasMemberLevelPermission || !workspaceProjectIds?.some((id) => canArrangeWork(id)),
          variant: "primary",
        },
      ]}
    />
  );
});
