/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { CircleUserRound } from "lucide-react";
import useSWR from "swr";
import { qualityApi } from "@/components/quality/api";
// plane imports
import { Avatar } from "@plane/ui";
// hooks
import { useUser } from "@/hooks/store/user";
import { getFileURL } from "@plane/utils";

export const ProfileSettingsSidebarHeader = observer(function ProfileSettingsSidebarHeader() {
  // store hooks
  const { data: currentUser } = useUser();

  const { data: account } = useSWR("/api/quality-auth/account-security/", (url: string) =>
    qualityApi.read<{ username: string; source_label: string }>(url)
  );

  return (
    <div className="flex shrink-0 items-center gap-2">
      <div className="shrink-0">
        {currentUser?.avatar_url ? (
          <Avatar src={getFileURL(currentUser.avatar_url)} name={account?.username} size={32} shape="circle" />
        ) : (
          <CircleUserRound className="size-8 text-secondary" />
        )}
      </div>
      <div className="truncate">
        <p className="truncate text-body-sm-medium">{account?.username || currentUser?.username || "账号"}</p>
        <p className="truncate text-caption-md-regular">{account?.source_label || ""}</p>
      </div>
    </div>
  );
});
