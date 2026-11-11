// SPDX-License-Identifier: AGPL-3.0-only
import { Outlet } from "react-router";
import { usePathname } from "next/navigation";
import { SettingsMobileNav } from "@/components/settings/mobile/nav";
import { WorkspaceSettingsSidebarRoot } from "@/components/settings/workspace/sidebar";
export default function PlatformSettingsLayout() {
  const path = usePathname();
  return (
    <>
      <SettingsMobileNav
        hamburgerContent={WorkspaceSettingsSidebarRoot}
        activePath=""
        displayLabel={
          path.endsWith("/models/")
            ? "模型配置"
            : path.endsWith("/connections/")
              ? "平台连接"
              : path.endsWith("/sources/")
                ? "来源关联"
                : "成员与权限"
        }
      />
      <div className="flex size-full">
        <div className="hidden h-full shrink-0 md:block">
          <WorkspaceSettingsSidebarRoot />
        </div>
        <Outlet />
      </div>
    </>
  );
}
