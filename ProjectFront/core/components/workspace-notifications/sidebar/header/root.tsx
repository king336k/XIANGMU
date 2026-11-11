/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { InboxIcon } from "@plane/propel/icons";
import { NotificationSidebarHeaderOptions } from "./options";
type TNotificationSidebarHeader = { workspaceSlug: string };
export const NotificationSidebarHeader = observer(function NotificationSidebarHeader({
  workspaceSlug,
}: TNotificationSidebarHeader) {
  if (!workspaceSlug) return null;
  return (
    <div className="flex w-full min-w-0 items-center justify-between gap-3 px-4 py-2 sm:px-6">
      <h1 className="flex shrink-0 items-center gap-2 text-14 font-medium text-primary">
        <InboxIcon className="size-4" />
        通知
      </h1>
      <div className="shrink-0">
        <NotificationSidebarHeaderOptions workspaceSlug={workspaceSlug} />
      </div>
    </div>
  );
});
