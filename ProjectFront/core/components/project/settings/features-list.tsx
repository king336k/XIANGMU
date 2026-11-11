/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { setPromiseToast } from "@plane/propel/toast";
import type { IProject } from "@plane/types";
import { CycleIcon, IntakeIcon, ModuleIcon, PageIcon, ViewsIcon } from "@plane/propel/icons";
// components
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useProject } from "@/hooks/store/use-project";
// plane web imports
// local imports
import { ProjectFeatureToggle } from "./helper";

type Props = {
  workspaceSlug: string;
  projectId: string;
  isAdmin: boolean;
};

const PROJECT_FEATURES_LIST = {
  cycles: {
    key: "cycles",
    property: "cycle_view",
    title: "周期",
    description: "按项目安排工作周期，并按需调整周期频率。",
    icon: <CycleIcon className="h-5 w-5 flex-shrink-0 rotate-180 text-tertiary" />,
    isPro: false,
    isEnabled: true,
  },
  modules: {
    key: "modules",
    property: "module_view",
    title: "模块",
    description: "将工作分组为模块，为每个模块设置模块负责人和任务执行人。",
    icon: <ModuleIcon width={20} height={20} className="flex-shrink-0 text-tertiary" />,
    isPro: false,
    isEnabled: true,
  },
  views: {
    key: "views",
    property: "issue_views_view",
    title: "视图",
    description: "保存排序、筛选和显示选项，供后续使用或分享。",
    icon: <ViewsIcon className="h-5 w-5 flex-shrink-0 text-tertiary" />,
    isPro: false,
    isEnabled: true,
  },
  pages: {
    key: "pages",
    property: "page_view",
    title: "文档",
    description: "自由编写和协作整理项目文档。",
    icon: <PageIcon className="h-5 w-5 flex-shrink-0 text-tertiary" />,
    isPro: false,
    isEnabled: true,
  },
  inbox: {
    key: "intake",
    property: "inbox_view",
    title: "需求收集",
    description: "在将工作项加入项目之前进行评估和讨论。",
    icon: <IntakeIcon className="h-5 w-5 flex-shrink-0 text-tertiary" />,
    isPro: false,
    isEnabled: true,
  },
};

export const ProjectFeaturesList = observer(function ProjectFeaturesList(props: Props) {
  const { workspaceSlug, projectId, isAdmin } = props;
  // store hooks
  const { t } = useTranslation();
  const { getProjectById, updateProject } = useProject();
  // derived values
  const currentProjectDetails = getProjectById(projectId);

  const handleSubmit = (_featureKey: string, featureProperty: string) => {
    if (!workspaceSlug || !projectId || !currentProjectDetails) return;

    // making the request to update the project feature
    const settingsPayload = {
      [featureProperty]: !currentProjectDetails?.[featureProperty as keyof IProject],
    };
    const updateProjectPromise = updateProject(workspaceSlug, projectId, settingsPayload);

    setPromiseToast(updateProjectPromise, {
      loading: "正在更新项目功能...",
      success: {
        title: "成功",
        message: () => "项目功能更新成功。",
      },
      error: {
        title: "错误",
        message: () => "项目功能更新失败，请重试。",
      },
    });
    void updateProjectPromise.then(() => {
      return undefined;
    });
  };

  return (
    <>
      <div>
        <SettingsHeading title={t("projects_and_issues")} description={t("projects_and_issues_description")} />
        <div className="mt-6 flex flex-col gap-y-4">
          {Object.entries(PROJECT_FEATURES_LIST).map(([featureItemKey, featureItem]) => (
            <div key={featureItemKey}>
              <SettingsBoxedControlItem
                title={<span className="flex items-center gap-2">{t(featureItem.key)}</span>}
                description={t(`${featureItem.key}_description`)}
                control={
                  <ProjectFeatureToggle
                    workspaceSlug={workspaceSlug}
                    projectId={projectId}
                    featureItem={featureItem}
                    value={Boolean(currentProjectDetails?.[featureItem.property as keyof IProject])}
                    handleSubmit={handleSubmit}
                    disabled={!isAdmin}
                  />
                }
              />
              {/* {currentProjectDetails?.[featureItem.property as keyof IProject] && (
                <div className="pl-14">{featureItem.renderChildren?.(currentProjectDetails, workspaceSlug)}</div>
              )} */}
            </div>
          ))}
        </div>
      </div>
    </>
  );
});
