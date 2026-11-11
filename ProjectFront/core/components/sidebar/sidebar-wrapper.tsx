/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
// plane helpers
import { useOutsideClickDetector } from "@plane/hooks";
import { PreferencesIcon } from "@plane/propel/icons";
import { ScrollArea } from "@plane/propel/scrollarea";
// components
import { CustomizeNavigationDialog } from "@/components/navigation/customize-navigation-dialog";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import useSize from "@/hooks/use-window-size";
// plane web components
import { AppSidebarToggleButton } from "./sidebar-toggle-button";

type TSidebarWrapperProps = {
  title: string;
  children: React.ReactNode;
  quickActions?: React.ReactNode;
};

export const SidebarWrapper = observer(function SidebarWrapper(props: TSidebarWrapperProps) {
  const { title, children, quickActions } = props;
  // state
  const [isCustomizeNavDialogOpen, setIsCustomizeNavDialogOpen] = useState(false);
  // store hooks
  const { toggleSidebar, sidebarCollapsed } = useAppTheme();
  const windowSize = useSize();
  // refs
  const ref = useRef<HTMLDivElement>(null);

  useOutsideClickDetector(ref, () => {
    if (sidebarCollapsed === false && window.innerWidth < 768) {
      toggleSidebar(true);
    }
  });

  useEffect(() => {
    if (windowSize[0] < 768 && !sidebarCollapsed) toggleSidebar(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowSize]);

  return (
    <>
      <CustomizeNavigationDialog isOpen={isCustomizeNavDialogOpen} onClose={() => setIsCustomizeNavDialogOpen(false)} />
      <div ref={ref} className="platform-sidebar flex h-full w-full animate-fade-in flex-col">
        {title !== "Projects" && (
          <div className="flex items-center justify-between px-5 pt-3 pb-1">
            <span className="text-16 font-medium text-primary">{title}</span>
            <AppSidebarToggleButton />
          </div>
        )}
        {quickActions && <div className="px-3 pt-3">{quickActions}</div>}

        <ScrollArea
          orientation="vertical"
          scrollType="hover"
          size="sm"
          rootClassName="min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
          viewportClassName="flex flex-col gap-0 overflow-x-hidden h-full w-full overflow-y-auto px-3 pt-3 pb-3"
        >
          {children}
        </ScrollArea>
        {title === "Projects" && (
          <div className="flex shrink-0 items-center justify-between border-t border-subtle px-3 py-2">
            <button
              type="button"
              onClick={() => setIsCustomizeNavDialogOpen(true)}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-12 text-secondary hover:bg-layer-transparent-hover"
            >
              <PreferencesIcon className="size-3.5" />
              自定义导航
            </button>
            <AppSidebarToggleButton />
          </div>
        )}
      </div>
    </>
  );
});
