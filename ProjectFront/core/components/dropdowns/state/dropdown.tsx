/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
// local imports
import type { TWorkItemStateDropdownBaseProps } from "./base";
import { WorkItemStateDropdownBase } from "./base";

type TWorkItemStateDropdownProps = Omit<
  TWorkItemStateDropdownBaseProps,
  "stateIds" | "getStateById" | "onDropdownOpen" | "isInitializing"
> & {
  stateIds?: string[];
};

export const StateDropdown = observer(function StateDropdown(props: TWorkItemStateDropdownProps) {
  const { projectId, stateIds: propsStateIds } = props;
  // router params
  const { workspaceSlug } = useParams();
  // states
  const [stateLoader, setStateLoader] = useState(false);
  const [loadError, setLoadError] = useState("");
  // store hooks
  const { fetchProjectStates, getProjectStateIds, getStateById } = useProjectState();
  // derived values
  const stateIds = propsStateIds ?? getProjectStateIds(projectId);

  // fetch states if not provided
  const onDropdownOpen = async () => {
    if ((stateIds === undefined || stateIds.length === 0) && workspaceSlug && projectId) {
      setStateLoader(true);
      setLoadError("");
      try {
        await fetchProjectStates(workspaceSlug.toString(), projectId);
      } catch {
        setLoadError("状态加载失败，请关闭后重试。");
      } finally {
        setStateLoader(false);
      }
    }
  };

  return (
    <WorkItemStateDropdownBase
      {...props}
      getStateById={getStateById}
      isInitializing={stateLoader}
      stateIds={stateIds ?? []}
      onDropdownOpen={onDropdownOpen}
      emptyMessage={loadError || "当前项目尚未配置状态"}
      settingsUrl={workspaceSlug && projectId ? `/${workspaceSlug}/settings/projects/${projectId}/states/` : undefined}
    />
  );
});
