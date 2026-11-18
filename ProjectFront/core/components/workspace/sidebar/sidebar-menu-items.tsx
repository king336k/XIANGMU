/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useEffect, useMemo } from "react";
import { observer } from "mobx-react";
// plane imports
import {
  WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS,
  WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS,
  WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS_LINKS,
  WORKSPACE_SIDEBAR_STATIC_PINNED_NAVIGATION_ITEMS_LINKS,
} from "@plane/constants";
// components
// store hooks
import { usePersonalNavigationPreferences } from "@/hooks/use-navigation-preferences";
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { SidebarItemBase } from "./sidebar-item";
import { RemoteDiagnosticsNavigationItem } from "@/components/remote-diagnostics/navigation-item";

export const SidebarMenuItems = observer(function SidebarMenuItems() {
  const { preferences: personalPreferences } = usePersonalNavigationPreferences();
  const { toggleExtendedSidebar } = useAppTheme();
  useEffect(() => toggleExtendedSidebar(false), [toggleExtendedSidebar]);

  // Filter static navigation items based on personal preferences
  const filteredStaticNavigationItems = useMemo(() => {
    const items = [...WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS_LINKS];
    const personalItems: Array<(typeof items)[0] & { sort_order: number }> = [];

    // Add personal items based on preferences with their sort_order
    const stickiesItem = WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS["stickies"];
    if (personalPreferences.items.stickies?.enabled && stickiesItem) {
      personalItems.push({
        ...stickiesItem,
        sort_order: personalPreferences.items.stickies.sort_order,
      });
    }
    if (personalPreferences.items.your_work?.enabled && WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS["your-work"]) {
      personalItems.push({
        ...WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS["your-work"],
        sort_order: personalPreferences.items.your_work.sort_order,
      });
    }
    if (personalPreferences.items.drafts?.enabled && WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS["drafts"]) {
      personalItems.push({
        ...WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS["drafts"],
        sort_order: personalPreferences.items.drafts.sort_order,
      });
    }

    // Sort personal items by sort_order
    personalItems.sort((a, b) => a.sort_order - b.sort_order);

    // Merge static items with sorted personal items
    return [...items, ...personalItems];
  }, [personalPreferences]);

  const primaryItems = [
    ...filteredStaticNavigationItems.filter((item) => item.key === "home" || item.key === "your_work"),
    ...WORKSPACE_SIDEBAR_STATIC_PINNED_NAVIGATION_ITEMS_LINKS,
    ...WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS.filter((item) => item.key !== "archives"),
  ];
  const personalRecordItems = filteredStaticNavigationItems.filter(
    (item) => item.key !== "home" && item.key !== "your_work"
  );
  const historicalItems = WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS.filter((item) => item.key === "archives");

  return (
    <div className="flex flex-col gap-0.5" aria-label="平台功能">
      {primaryItems.map((item) => (
        <Fragment key={item.key}>
          <SidebarItemBase item={item} />
          {item.key === "analytics" && <RemoteDiagnosticsNavigationItem />}
        </Fragment>
      ))}
      {personalRecordItems.length > 0 && (
        <div className="mt-2 flex flex-col gap-0.5 border-t border-subtle pt-2" aria-label="个人记录">
          {personalRecordItems.map((item) => (
            <SidebarItemBase key={item.key} item={item} />
          ))}
        </div>
      )}
      {historicalItems.map((item) => (
        <SidebarItemBase key={item.key} item={item} />
      ))}
    </div>
  );
});
