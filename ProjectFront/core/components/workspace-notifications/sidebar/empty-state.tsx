/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { ENotificationTab } from "@plane/constants";
import { EmptyStateCompact } from "@plane/propel/empty-state";

type TNotificationEmptyStateProps = {
  currentNotificationTab: ENotificationTab;
  readStatus?: "all" | "read" | "unread";
};

export const NotificationEmptyState = observer(function NotificationEmptyState({
  currentNotificationTab,
  readStatus = "all",
}: TNotificationEmptyStateProps) {
  // plane imports

  return (
    <>
      <EmptyStateCompact
        assetKey="inbox"
        assetClassName="size-24"
        title={
          currentNotificationTab === ENotificationTab.MENTIONS
            ? "暂无提及你的通知"
            : readStatus === "unread"
              ? "暂无未读通知"
              : readStatus === "read"
                ? "暂无已读通知"
                : "暂无通知"
        }
        className="max-w-56"
      />
    </>
  );
});
