/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { ScrollArea } from "@plane/propel/scrollarea";
import type { TProfileSettingsTabs } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { ProfileSettingsSidebarHeader } from "./header";
import { ProfileSettingsSidebarItemCategories } from "./item-categories";
import { PlatformAbout } from "@/components/global/platform-about";
import { useState } from "react";
import { useUser } from "@/hooks/store/user";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";

type Props = {
  activeTab: TProfileSettingsTabs;
  className?: string;
  updateActiveTab: (tab: TProfileSettingsTabs) => void;
};

export function ProfileSettingsSidebarRoot(props: Props) {
  const { activeTab, className, updateActiveTab } = props;
  const { signOut } = useUser();
  const [leaving, setLeaving] = useState(false);

  return (
    <ScrollArea
      scrollType="hover"
      orientation="vertical"
      size="sm"
      rootClassName={cn("shrink-0 overflow-y-scroll border-r border-r-subtle bg-surface-2 px-3 py-4", className)}
    >
      <ProfileSettingsSidebarHeader />
      <ProfileSettingsSidebarItemCategories activeTab={activeTab} updateActiveTab={updateActiveTab} />
      <button
        type="button"
        disabled={leaving}
        className="mt-5 w-full rounded px-2 py-2 text-left text-12 text-secondary hover:bg-layer-1"
        onClick={async () => {
          setLeaving(true);
          try {
            await signOut();
          } catch {
            setLeaving(false);
            setToast({ type: TOAST_TYPE.ERROR, title: "退出失败，请重试" });
          }
        }}
      >
        {leaving ? "正在退出…" : "退出登录"}
      </button>
      <PlatformAbout />
    </ScrollArea>
  );
}
