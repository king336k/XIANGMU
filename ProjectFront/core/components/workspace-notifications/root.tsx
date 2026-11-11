/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { ENotificationLoader, ENotificationQueryParamType } from "@plane/constants";
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { NotificationsSidebarRoot } from "./sidebar";

type NotificationsRootProps = { workspaceSlug?: string };
export const NotificationsRoot = observer(function NotificationsRoot({ workspaceSlug }: NotificationsRootProps) {
  const { currentWorkspace } = useWorkspace();
  const { notificationIdsByWorkspaceId, getNotifications } = useWorkspaceNotifications();
  const initialized = currentWorkspace && notificationIdsByWorkspaceId(currentWorkspace.id);
  useSWR(
    workspaceSlug ? `WORKSPACE_NOTIFICATION_${workspaceSlug}` : null,
    workspaceSlug
      ? () =>
          getNotifications(
            workspaceSlug,
            initialized ? ENotificationLoader.MUTATION_LOADER : ENotificationLoader.INIT_LOADER,
            initialized ? ENotificationQueryParamType.CURRENT : ENotificationQueryParamType.INIT
          )
      : null
  );
  return <NotificationsSidebarRoot />;
});
