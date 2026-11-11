/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { PanelLeft } from "lucide-react";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { IconButton } from "@plane/propel/icon-button";

export const AppSidebarToggleButton = observer(function AppSidebarToggleButton({
  onlyWhenCollapsed = false,
}: {
  onlyWhenCollapsed?: boolean;
}) {
  // store hooks
  const { toggleSidebar, sidebarPeek, toggleSidebarPeek, sidebarCollapsed } = useAppTheme();
  if (onlyWhenCollapsed && !sidebarCollapsed) return null;

  return (
    <IconButton
      aria-label={sidebarCollapsed ? "展开项目导航" : "收起项目导航"}
      size="base"
      variant="ghost"
      icon={PanelLeft}
      onClick={() => {
        if (sidebarPeek) toggleSidebarPeek(false);
        toggleSidebar();
      }}
    />
  );
});
