// SPDX-License-Identifier: AGPL-3.0-only
import { observer } from "mobx-react";
import useSWR from "swr";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { Users, Plug, Settings2, Link2 } from "lucide-react";
import { qualityApi } from "@/components/quality/api";
import { SettingsSidebarItem } from "@/components/settings/sidebar/item";
import { useProject } from "@/hooks/store/use-project";
import { useSettingsPermissions } from "@/components/settings/use-settings-permissions";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
export const WorkspaceSettingsSidebarItemCategories = observer(function WorkspaceSettingsSidebarItemCategories() {
  const { workspaceSlug, projectId } = useParams();
  const pathname = usePathname();
  const params = useSearchParams();
  const { joinedProjectIds, getPartialProjectById } = useProject();
  const { allowPermissions } = useSettingsPermissions();
  const selected = projectId || params.get("project") || "";
  const activeProject = joinedProjectIds.includes(String(selected)) ? String(selected) : "";
  const preserved = new URLSearchParams(params);
  if (activeProject) preserved.set("project", activeProject);
  const query = preserved.size ? `?${preserved}` : "";
  const { data: accountAccess } = useSWR("/api/quality-auth/accounts/?per_page=1", (url: string) =>
    qualityApi.read<{ can_manage_administrators?: boolean }>(url)
  );
  const administrator = accountAccess?.can_manage_administrators === true;
  const links = [
    { key: "members", label: "成员与权限", icon: Users },
    { key: "sources", label: "协作服务", icon: Link2 },
    ...(administrator
      ? [
          { key: "daq-projects", label: "DAQ 项目授权", icon: Link2 },
          { key: "connections", label: "平台连接", icon: Plug },
          { key: "models", label: "模型配置", icon: Settings2 },
        ]
      : []),
  ];
  return (
    <nav aria-label="设置导航" className="mt-3 space-y-3 px-3">
      {links.map((item) => (
        <SettingsSidebarItem
          key={item.key}
          as="link"
          href={`/${workspaceSlug}/settings/${item.key}/${query}`}
          isActive={pathname === `/${workspaceSlug}/settings/${item.key}/`}
          icon={item.icon}
          label={item.label}
        />
      ))}
      <details className="border-t border-subtle pt-3">
        <summary className="cursor-pointer px-2 text-13 text-secondary">其他配置</summary>
        <div className="mt-2 flex flex-col gap-1">
          <SettingsSidebarItem
            as="link"
            href={`/${workspaceSlug}/settings/`}
            isActive={pathname === `/${workspaceSlug}/settings/`}
            icon={Settings2}
            label="工作空间信息"
          />
          <SettingsSidebarItem
            as="link"
            href={`/${workspaceSlug}/settings/exports/`}
            isActive={pathname.endsWith("/exports/")}
            icon={Settings2}
            label="导出"
          />
          {administrator && (
            <SettingsSidebarItem
              as="link"
              href={`/${workspaceSlug}/settings/webhooks/`}
              isActive={pathname.includes("/webhooks/")}
              icon={Link2}
              label="事件通知接口"
            />
          )}
          <label className="px-2 py-1 text-12">
            项目
            <select
              aria-label="选择项目配置"
              className="mt-1 w-full rounded border border-subtle bg-surface-1 p-2"
              value={activeProject}
              onChange={(event) => {
                const url = new URL(window.location.href);
                url.pathname = `/${workspaceSlug}/settings/members/`;
                url.searchParams.set("project", event.target.value);
                window.location.assign(url.pathname + url.search + url.hash);
              }}
            >
              <option value="">请选择项目</option>
              {joinedProjectIds.map((id) => (
                <option key={id} value={id}>
                  {getPartialProjectById(id)?.name || id}
                </option>
              ))}
            </select>
          </label>
          {activeProject &&
            [
              { path: "", label: "项目信息" },
              { path: "features/cycles", label: "迭代周期" },
              { path: "features/modules", label: "功能模块" },
              { path: "features/views", label: "任务视图" },
              { path: "features/pages", label: "项目文档" },
              { path: "features/intake", label: "待评估事项" },
              { path: "states", label: "状态" },
              { path: "labels", label: "标签" },
              { path: "estimates", label: "工作量预估" },
              { path: "automations", label: "自动化" },
            ]
              .filter(
                (item) =>
                  !item.path ||
                  allowPermissions(
                    [EUserPermissions.ADMIN],
                    EUserPermissionsLevel.PROJECT,
                    String(workspaceSlug),
                    activeProject
                  ) ||
                  (["states", "labels"].includes(item.path) &&
                    allowPermissions(
                      [EUserPermissions.MEMBER],
                      EUserPermissionsLevel.PROJECT,
                      String(workspaceSlug),
                      activeProject
                    ))
              )
              .map((item) => (
                <SettingsSidebarItem
                  key={item.path}
                  as="link"
                  href={`/${workspaceSlug}/settings/projects/${activeProject}/${item.path ? `${item.path}/` : ""}`}
                  isActive={
                    pathname ===
                    `/${workspaceSlug}/settings/projects/${activeProject}/${item.path ? `${item.path}/` : ""}`
                  }
                  icon={Settings2}
                  label={item.label}
                />
              ))}
        </div>
      </details>
    </nav>
  );
});
