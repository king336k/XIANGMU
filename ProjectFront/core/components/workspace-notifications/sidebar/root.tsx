/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { ENotificationTab } from "@plane/constants";
import { Header, Row, ERowVariant, EHeaderVariant, ContentWrapper } from "@plane/ui";
import { cn, getNumberCount } from "@plane/utils";
// components
import { CountChip } from "@/components/common/count-chip";
// hooks
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { useWorkspace } from "@/hooks/store/use-workspace";
// local imports
import { NotificationEmptyState } from "./empty-state";
import { AppliedFilters } from "./filters/applied-filter";
import { NotificationSidebarHeader } from "./header";
import { NotificationsLoader } from "./loader";
import { NotificationCardListRoot } from "../notification-card/root";

export const NotificationsSidebarRoot = observer(function NotificationsSidebarRoot() {
  const { workspaceSlug } = useParams();
  // hooks
  const { getWorkspaceBySlug } = useWorkspace();
  const {
    unreadNotificationsCount,
    loader,
    notificationIdsByWorkspaceId,
    currentNotificationTab,
    filters,
    setNotificationView,
  } = useWorkspaceNotifications();

  // derived values
  const workspace = workspaceSlug ? getWorkspaceBySlug(workspaceSlug.toString()) : undefined;
  const notificationIds = workspace ? notificationIdsByWorkspaceId(workspace.id) : undefined;

  if (!workspaceSlug || !workspace) return <></>;

  return (
    <div className={cn("relative h-full w-full min-w-0 bg-surface-1")}>
      <div className="relative flex h-full w-full flex-col">
        <Row className="flex h-header flex-shrink-0 border-b border-subtle">
          <NotificationSidebarHeader workspaceSlug={workspaceSlug.toString()} />
        </Row>

        <Header variant={EHeaderVariant.SECONDARY} className="justify-start">
          {[
            { key: "all", title: "全部" },
            { key: "unread", title: "未读" },
            { key: "read", title: "已读" },
            { key: "mentions", title: "提及" },
          ].map((tab) => {
            const readStatus = filters.read_status || (filters.read ? "unread" : "all");
            const active =
              tab.key === "mentions"
                ? currentNotificationTab === ENotificationTab.MENTIONS
                : currentNotificationTab === ENotificationTab.ALL && readStatus === tab.key;
            return (
              <button
                type="button"
                key={tab.key}
                aria-pressed={active}
                className={cn(
                  "relative flex h-full items-center gap-1 px-3 text-13 font-medium",
                  active ? "border-b-2 border-accent-strong text-accent-primary" : "text-secondary hover:text-primary"
                )}
                onClick={() => {
                  setNotificationView(
                    tab.key === "mentions" ? ENotificationTab.MENTIONS : ENotificationTab.ALL,
                    tab.key === "read" ? "read" : tab.key === "unread" ? "unread" : "all"
                  );
                }}
              >
                {tab.title}
                {tab.key === "unread" && unreadNotificationsCount.total_unread_notifications_count > 0 && (
                  <CountChip count={getNumberCount(unreadNotificationsCount.total_unread_notifications_count)} />
                )}
              </button>
            );
          })}
        </Header>

        {/* applied filters */}
        <AppliedFilters workspaceSlug={workspaceSlug.toString()} />

        {/* rendering notifications */}
        {loader === "init-loader" ? (
          <div className="relative h-full w-full overflow-hidden">
            <NotificationsLoader />
          </div>
        ) : (
          <>
            {notificationIds && notificationIds.length > 0 ? (
              <ContentWrapper variant={ERowVariant.HUGGING}>
                <NotificationCardListRoot workspaceSlug={workspaceSlug.toString()} workspaceId={workspace?.id} />
              </ContentWrapper>
            ) : (
              <div className="relative flex h-full w-full items-center justify-center">
                <NotificationEmptyState
                  currentNotificationTab={currentNotificationTab}
                  readStatus={filters.read_status || (filters.read ? "unread" : "all")}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
});
