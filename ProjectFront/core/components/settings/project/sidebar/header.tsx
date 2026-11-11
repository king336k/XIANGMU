/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { qualityApi } from "@/components/quality/api";
import { projectDutySummary } from "@/components/quality/duty-summary";
import type { Context } from "@/components/quality/types";
import { ArrowLeft } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { observer } from "mobx-react";
// plane imports
import { ROLE_DETAILS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { IconButton } from "@plane/propel/icon-button";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { useProject } from "@/hooks/store/use-project";
import { useWorkspace } from "@/hooks/store/use-workspace";

type Props = {
  projectId: string;
};

export const ProjectSettingsSidebarHeader = observer(function ProjectSettingsSidebarHeader(props: Props) {
  const { projectId } = props;
  // router
  const router = useAppRouter();
  // store hooks
  const { getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();
  const { currentWorkspace } = useWorkspace();
  const { getPartialProjectById, joinedProjectIds } = useProject();
  const pathname = usePathname();
  const query = useSearchParams();
  // derived values
  const projectDetails = getPartialProjectById(projectId);
  const { data: context } = useSWR(
    currentWorkspace?.slug ? `/api/workspaces/${currentWorkspace.slug}/projects/${projectId}/quality/context/` : null,
    (url: string) => qualityApi.read<Context>(url)
  );
  const currentProjectRole = currentWorkspace?.slug
    ? getProjectRoleByWorkspaceSlugAndProjectId(currentWorkspace.slug, projectId)
    : undefined;
  // translation
  const { t } = useTranslation();

  if (!currentProjectRole) return null;

  return (
    <div className="shrink-0">
      <div className="flex items-center gap-1 py-3 pr-5 pl-4 text-body-md-medium">
        <IconButton
          variant="ghost"
          size="base"
          icon={ArrowLeft}
          onClick={() => router.push(`/${currentWorkspace?.slug}/projects/${projectId}/issues/`)}
        />
        <p>项目设置</p>
      </div>
      <label className="mx-4 my-2 flex flex-col gap-1 text-12 text-secondary">
        项目
        <select
          aria-label="切换设置项目"
          className="rounded border border-subtle bg-surface-1 p-2 text-primary"
          value={projectId}
          onChange={(event) =>
            router.push(
              `${pathname.replace(`/projects/${projectId}`, `/projects/${event.target.value}`)}${query.size ? `?${query}` : ""}`
            )
          }
        >
          {joinedProjectIds.map((id) => (
            <option key={id} value={id}>
              {getPartialProjectById(id)?.name || id}
            </option>
          ))}
        </select>
      </label>
      <div className="mt-1.5 flex items-center gap-2 truncate px-5 py-0.5">
        <div className="grid size-8 shrink-0 place-items-center rounded bg-layer-2">
          <Logo logo={projectDetails?.logo_props} size={20} />
        </div>
        <div className="truncate">
          <p className="truncate text-body-sm-medium">{projectDetails?.name}</p>
          <p className="truncate text-caption-md-regular">
            {context
              ? projectDutySummary((context.business_role_name || "项目成员").split("、")).label
              : t(ROLE_DETAILS[currentProjectRole].i18n_title)}
          </p>
        </div>
      </div>
    </div>
  );
});
