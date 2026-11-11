// SPDX-License-Identifier: AGPL-3.0-only
import useSWR from "swr";
import { useParams } from "next/navigation";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useUserPermissions } from "@/hooks/store/user";
import { qualityApi } from "@/components/quality/api";
import { canManageSettings } from "./settings-permissions";
// This adapter is restricted to the Settings UI; business capabilities use their existing context.
export function useSettingsPermissions() {
  const permissions = useUserPermissions();
  const params = useParams();
  const { data, error } = useSWR("/api/quality-auth/accounts/?per_page=1", (url: string) =>
    qualityApi.read<{ can_manage_administrators?: boolean }>(url)
  );
  const allowPermissions: typeof permissions.allowPermissions = (wanted, level, workspace, project, onAllowed) => {
    const native = permissions.allowPermissions(wanted, level, workspace, project, onAllowed);
    if (native || !wanted.includes(EUserPermissions.ADMIN)) return native;
    const slug = workspace || params.workspaceSlug;
    const id = project || params.projectId;
    if (!slug) return native;
    const workspaceRole = permissions.getWorkspaceRoleByWorkspaceSlug(String(slug));
    const projectRole =
      level === EUserPermissionsLevel.PROJECT
        ? id
          ? (permissions.getProjectRoleByWorkspaceSlugAndProjectId(String(slug), String(id)) ?? 0)
          : 0
        : undefined;
    const allowed = canManageSettings(native, !error && data?.can_manage_administrators, workspaceRole, projectRole);
    return allowed && (!onAllowed || onAllowed());
  };
  return { workspaceUserInfo: permissions.workspaceUserInfo, allowPermissions };
}
