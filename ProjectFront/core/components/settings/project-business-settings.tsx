// SPDX-License-Identifier: AGPL-3.0-only
import { ProjectRouteLink } from "@/components/common/project-route-link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { AccountManager } from "@/components/quality/account-manager";
import { BusinessRolePanel } from "@/components/quality/business-role-panel";
import { IntegrationsPanel } from "@/components/quality/integrations-panel";
import { canOpenQualityTab } from "@/components/quality/types";
import type { Context } from "@/components/quality/types";
export function ProjectBusinessSettings({ section, selectedProjectId }: { section: "members" | "sources";selectedProjectId?:string }) {
  const { workspaceSlug, projectId:routeProjectId } = useParams();
  const projectId=selectedProjectId||routeProjectId;
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/`;
  const { data: context, error, mutate } = useSWR(`${base}context/`, (url: string) => qualityApi.read<Context>(url));
  if (error)
    return (
      <p role="alert" className="text-13 text-danger-primary">
        {errorMessage(error)}
      </p>
    );
  if (!context)
    return (
      <p role="status" className="text-13 text-secondary">
        正在读取项目权限…
      </p>
    );
  if (!canOpenQualityTab(context, section === "members" ? "roles" : "integrations"))
    return (
      <p role="alert" className="text-13 text-secondary">
        当前账号没有此管理权限。
      </p>
    );
  return section === "members" ? (
    <>
      <BusinessRolePanel key={projectId} base={base} context={context} onSaved={mutate} includeAccounts={false} />
      <AccountManager
        key={`${projectId}:accounts`}
        project={{ workspace: String(workspaceSlug), id: String(projectId) }}
        projectOnly
        onSaved={mutate}
      />
    </>
  ) : (
    <>
      {context.is_administrator && (
        <ProjectRouteLink
          className="mb-4 inline-block text-13 text-accent-primary"
          to={`/${workspaceSlug}/settings/connections/?project=${projectId}`}
        >
          平台连接
        </ProjectRouteLink>
      )}
      <IntegrationsPanel key={projectId} base={base} context={context} includeConnections={false} />
    </>
  );
}
