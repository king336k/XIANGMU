/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { observer } from "mobx-react";
import { PinOff } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
// plane imports
import type { IWorkspaceSidebarNavigationItem } from "@plane/constants";
import { EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { joinUrlPath } from "@plane/utils";
// components
import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useUser, useUserPermissions } from "@/hooks/store/user";
import { useWorkspaceNavigationPreferences } from "@/hooks/use-navigation-preferences";
// plane web imports
import { getSidebarNavigationItemIcon } from "@/components/workspace/sidebar/helper";

type Props = {
  item: IWorkspaceSidebarNavigationItem;
  additionalRender?: (itemKey: string, workspaceSlug: string) => ReactNode;
  additionalStaticItems?: string[];
};

export const SidebarItemBase = observer(function SidebarItemBase({
  item,
  additionalRender,
  additionalStaticItems,
}: Props) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const { workspaceSlug } = useParams();
  const { allowPermissions } = useUserPermissions();
  const { isWorkspaceItemPinned, toggleWorkspaceItem } = useWorkspaceNavigationPreferences();
  const { data } = useUser();

  const { toggleSidebar, isExtendedSidebarOpened, toggleExtendedSidebar } = useAppTheme();

  const handleLinkClick = () => {
    if (window.innerWidth < 768) toggleSidebar();
    if (isExtendedSidebarOpened) toggleExtendedSidebar(false);
  };

  const staticItems = new Set([
    "home",
    "pi_chat",
    "projects",
    "your_work",
    "stickies",
    "drafts",
    "views",
    "analytics",
    "archives",
    ...(additionalStaticItems || []),
  ]);
  const slug = workspaceSlug?.toString() || "";

  if (!allowPermissions(item.access, EUserPermissionsLevel.WORKSPACE, slug)) return null;

  const isPinned = isWorkspaceItemPinned(item.key);
  if (!isPinned && !staticItems.has(item.key)) return null;

  const itemHref = item.key === "your_work" && data?.id ? `/${slug}/my-work/` : joinUrlPath(slug, item.href);
  const icon = getSidebarNavigationItemIcon(item.key);

  return (
    <SidebarNavItem isActive={item.highlight(pathname, itemHref)}>
      <Link
        href={itemHref}
        aria-current={item.highlight(pathname, itemHref) ? "page" : undefined}
        onClick={handleLinkClick}
        className="min-w-0 flex-1"
      >
        <div className="flex items-center gap-1.5 py-[1px]">
          {icon}
          <p className="text-13 leading-5 font-medium">{t(item.labelTranslationKey)}</p>
        </div>
      </Link>
      {additionalRender?.(item.key, slug)}
      {!staticItems.has(item.key) && isPinned && (
        <button
          type="button"
          aria-label={`取消固定${t(item.labelTranslationKey)}`}
          title="取消固定"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            toggleWorkspaceItem(item.key, false);
          }}
          className="rounded p-1 text-placeholder hover:bg-layer-1"
        >
          <PinOff className="size-3" />
        </button>
      )}
    </SidebarNavItem>
  );
});
