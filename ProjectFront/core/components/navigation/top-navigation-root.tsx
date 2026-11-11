/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { useLocation, useNavigate } from "react-router";
import { cn } from "@plane/utils";
import { TopNavPowerK } from "@/components/navigation";
import { HelpMenuRoot } from "@/components/workspace/sidebar/help-section/root";
import { UserMenuRoot } from "@/components/workspace/sidebar/user-menu-root";
import { WorkspaceMenuRoot } from "@/components/workspace/sidebar/workspace-menu-root";
import { PlatformLogo } from "@/components/common/platform-logo";
import { useAppRailPreferences } from "@/hooks/use-navigation-preferences";
import { Tooltip } from "@plane/propel/tooltip";
import { InboxIcon } from "@plane/propel/icons";
import useSWR from "swr";
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { notificationNavigation } from "./notification-navigation";
// local imports

export const TopNavigationRoot = observer(function TopNavigationRoot() {
  // router
  const { workspaceSlug } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const notification = notificationNavigation(workspaceSlug?.toString() ?? "", location);

  // store hooks
  const { unreadNotificationsCount, getUnreadNotificationsCount } = useWorkspaceNotifications();
  const { preferences } = useAppRailPreferences();

  const showLabel = preferences.displayMode === "icon_with_label";

  // Fetch notification count
  useSWR(
    workspaceSlug ? `WORKSPACE_UNREAD_NOTIFICATION_COUNT_${workspaceSlug}` : null,
    workspaceSlug ? () => getUnreadNotificationsCount(workspaceSlug.toString()) : null
  );

  // Calculate notification count
  const totalNotifications = Math.max(
    unreadNotificationsCount.total_unread_notifications_count || 0,
    unreadNotificationsCount.mention_unread_notifications_count || 0
  );

  return (
    <div
      className={cn(
        "z-[27] flex min-h-14 w-full items-center gap-2 border-b border-subtle bg-surface-1 px-2 transition-all duration-300 sm:gap-4 sm:px-4",
        {
          "px-2": !showLabel,
        }
      )}
    >
      {/* Workspace Menu */}
      <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-4">
        <a href={`/${workspaceSlug}/`} className="hidden shrink-0 sm:block" aria-label="平台首页">
          <PlatformLogo className="h-8 w-auto" />
        </a>
        <WorkspaceMenuRoot variant="top-navigation" />
      </div>
      {/* Power K Search */}
      <div className="shrink-0">
        <TopNavPowerK />
      </div>
      {/* Additional Actions */}
      <div className="flex shrink-0 items-center justify-end gap-1 sm:flex-1">
        <Tooltip tooltipContent={notification.label} position="bottom">
          <button
            type="button"
            aria-label={notification.label}
            aria-pressed={notification.isInbox}
            disabled={!workspaceSlug}
            onClick={() => navigate(notification.to, { state: notification.state })}
            className={cn(
              "grid size-8 place-items-center rounded-md text-tertiary hover:bg-layer-1 hover:text-primary",
              {
                "bg-layer-1 text-primary": notification.isInbox,
              }
            )}
          >
            <div className="relative">
              <InboxIcon className="size-5" />
              {totalNotifications > 0 && (
                <span
                  aria-label={`${totalNotifications} 条未读通知`}
                  className="absolute -top-1.5 -right-2 grid h-4 min-w-4 place-items-center rounded-full bg-danger-primary px-1 text-9 leading-none font-medium text-on-color"
                >
                  {totalNotifications > 99 ? "99+" : totalNotifications}
                </span>
              )}
            </div>
          </button>
        </Tooltip>
        <HelpMenuRoot />
        <div className="flex h-8 min-w-8 items-center justify-center rounded-md hover:bg-layer-1-hover">
          <UserMenuRoot />
        </div>
      </div>
    </div>
  );
});
