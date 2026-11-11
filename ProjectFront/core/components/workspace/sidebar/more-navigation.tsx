import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
// SPDX-License-Identifier: AGPL-3.0-only
import { observer } from "mobx-react";
import { useParams } from "react-router";
import { useEffect, useState } from "react";
import { Ellipsis, Pin } from "lucide-react";
import { WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Popover } from "@plane/propel/popover";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useWorkspaceNavigationPreferences } from "@/hooks/use-navigation-preferences";
import { getSidebarNavigationItemIcon } from "./helper";

export const MoreNavigation = observer(function MoreNavigation() {
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  const { allowPermissions } = useUserPermissions();
  const { preferences, toggleWorkspaceItem } = useWorkspaceNavigationPreferences();
  const { toggleExtendedSidebar } = useAppTheme();
  useEffect(() => toggleExtendedSidebar(false), [toggleExtendedSidebar]);
  const [open, setOpen] = useState(false);
  const items = WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS.filter(
    (item) =>
      !preferences.items[item.key]?.is_pinned &&
      allowPermissions(item.access, EUserPermissionsLevel.WORKSPACE, workspaceSlug || "")
  );
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Button
        className="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-13 text-secondary hover:bg-layer-1"
        aria-label="更多导航"
      >
        <Ellipsis className="size-4" />
        更多
      </Popover.Button>
      <Popover.Panel
        side="right"
        align="start"
        className="shadow-lg z-50 w-56 rounded-md border border-subtle bg-surface-1 p-1.5"
        aria-label="更多导航"
      >
        {items.length === 0 && <p className="px-3 py-2 text-12 text-secondary">所有入口已固定到侧栏</p>}
        {items.map((item) => (
          <div key={item.key} className="flex items-center gap-1 rounded hover:bg-layer-1">
            <Link
              to={`/${workspaceSlug}${item.href}`}
              onClick={() => {
                setOpen(false);
                toggleExtendedSidebar(false);
              }}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-13"
            >
              {getSidebarNavigationItemIcon(item.key)}
              {t(item.labelTranslationKey)}
            </Link>
            <button
              type="button"
              title="固定到侧栏"
              aria-label={`固定${t(item.labelTranslationKey)}到侧栏`}
              onClick={() => toggleWorkspaceItem(item.key, true)}
              className="mr-1 rounded p-1.5 text-secondary hover:bg-layer-2"
            >
              <Pin className="size-3.5" />
            </button>
          </div>
        ))}
      </Popover.Panel>
    </Popover>
  );
});
