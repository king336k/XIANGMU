/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FC, ReactNode } from "react";
import {
  RotateCcw,
  Network,
  Inbox,
  AlignLeft,
  Paperclip,
  Type,
  FileText,
  Hash,
  Clock,
  Bell,
  GitBranch,
  Timer,
  ListTodo,
  Layers,
} from "lucide-react";
// components

import {
  LinkIcon,
  ArchiveIcon,
  CycleIcon,
  GlobeIcon,
  DueDatePropertyIcon,
  EstimatePropertyIcon,
  GridLayoutIcon,
  IntakeIcon,
  LabelPropertyIcon,
  MembersPropertyIcon,
  ModuleIcon,
  PriorityPropertyIcon,
  StartDatePropertyIcon,
  StatePropertyIcon,
} from "@plane/propel/icons";
import { store } from "@/lib/store-context";
import type { TProjectActivity } from "@plane/types";

type ActivityIconMap = {
  [key: string]: FC<{ className?: string }>;
};
export const iconsMap: ActivityIconMap = {
  priority: PriorityPropertyIcon,
  archived_at: ArchiveIcon,
  restored: RotateCcw,
  link: LinkIcon,
  start_date: StartDatePropertyIcon,
  target_date: DueDatePropertyIcon,
  label: LabelPropertyIcon,
  inbox: Inbox,
  description: AlignLeft,
  assignee: MembersPropertyIcon,
  attachment: Paperclip,
  name: Type,
  state: StatePropertyIcon,
  estimate: EstimatePropertyIcon,
  cycle: CycleIcon,
  module: ModuleIcon,
  page: FileText,
  network: GlobeIcon,
  identifier: Hash,
  timezone: Clock,
  is_project_updates_enabled: Bell,
  is_epic_enabled: GridLayoutIcon,
  is_workflow_enabled: GitBranch,
  is_time_tracking_enabled: Timer,
  is_issue_type_enabled: ListTodo,
  default: Network,
  module_view: ModuleIcon,
  cycle_view: CycleIcon,
  issue_views_view: Layers,
  page_view: FileText,
  intake_view: IntakeIcon,
};

export const messages = (activity: TProjectActivity): { message: string | ReactNode; customUserName?: string } => {
  const activityType = activity.field;
  const newValue = activity.new_value;
  const oldValue = activity.old_value;
  const verb = activity.verb;
  const actionLabel =
    (
      {
        created: "创建了",
        updated: "更新了",
        removed: "移除了",
        deleted: "删除了",
        added: "添加了",
        enabled: "启用了",
        disabled: "禁用了",
      } as Record<string, string>
    )[verb] ?? verb;
  const workspaceDetail = store.workspaceRoot.getWorkspaceById(activity.workspace);

  const getBooleanActionText = (value: string | undefined) => {
    if (value === "true") return "启用了";
    if (value === "false") return "禁用了";
    return actionLabel;
  };

  switch (activityType) {
    case "priority":
      return {
        message: (
          <>
            将优先级设为 <span className="font-medium text-primary">{newValue || "无"}</span>
          </>
        ),
      };
    case "archived_at":
      return {
        message: newValue === "restore" ? "恢复了项目" : "归档了项目",
        customUserName: newValue === "archive" ? "系统" : undefined,
      };
    case "name":
      return {
        message: (
          <>
            将项目重命名为 <span className="font-medium text-primary">{newValue}</span>
          </>
        ),
      };
    case "description":
      return {
        message: newValue ? "更新了项目描述" : "移除了项目描述",
      };
    case "start_date":
      return {
        message: (
          <>
            {newValue ? (
              <>
                将开始日期设为 <span className="font-medium text-primary">{newValue}</span>
              </>
            ) : (
              "移除了开始日期"
            )}
          </>
        ),
      };
    case "target_date":
      return {
        message: (
          <>
            {newValue ? (
              <>
                将目标日期设为 <span className="font-medium text-primary">{newValue}</span>
              </>
            ) : (
              "移除了目标日期"
            )}
          </>
        ),
      };
    case "state":
      return {
        message: (
          <>
            将状态设为 <span className="font-medium text-primary">{newValue || "无"}</span>
          </>
        ),
      };
    case "estimate":
      return {
        message: (
          <>
            {newValue ? (
              <>
                将估点设为 <span className="font-medium text-primary">{newValue}</span>
              </>
            ) : (
              <>
                移除了估点
                {oldValue && (
                  <>
                    {" "}
                    <span className="font-medium text-primary">{oldValue}</span>
                  </>
                )}
              </>
            )}
          </>
        ),
      };
    case "cycles":
      return {
        message: (
          <>
            <span>
              {actionLabel} 此项目 {verb === "removed" ? "从" : "到"} 周期{" "}
            </span>
            {verb !== "removed" ? (
              <a
                href={`/${workspaceDetail?.slug}/projects/${activity.project}/cycles/${activity.new_identifier}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex font-medium text-primary"
              >
                {activity.new_value}
              </a>
            ) : (
              <span className="font-medium text-primary">{activity.old_value || "未知周期"}</span>
            )}
          </>
        ),
      };
    case "modules":
      return {
        message: (
          <>
            <span>
              {actionLabel} 此项目 {verb === "removed" ? "从" : "到"} 模块{" "}
            </span>
            <span className="font-medium text-primary">{verb === "removed" ? oldValue : newValue || "未知模块"}</span>
          </>
        ),
      };
    case "labels":
      return {
        message: (
          <>
            {actionLabel} 标签 <span className="font-medium text-primary">{newValue || oldValue || "未命名标签"}</span>
          </>
        ),
      };
    case "inbox":
      return {
        message: <>{newValue ? "启用了" : "禁用了"} 需求收集</>,
      };
    case "page":
      return {
        message: (
          <>
            {newValue ? "创建了" : "移除了"} 项目文档{" "}
            <span className="font-medium text-primary">{newValue || oldValue || "未命名文档"}</span>
          </>
        ),
      };
    case "network":
      return {
        message: <>{newValue ? "启用了" : "禁用了"} 访问权限</>,
      };
    case "identifier":
      return {
        message: (
          <>
            将项目标识符更新为 <span className="font-medium text-primary">{newValue || "无"}</span>
          </>
        ),
      };
    case "timezone":
      return {
        message: (
          <>
            将项目时区更改为 <span className="font-medium text-primary">{newValue || "默认"}</span>
          </>
        ),
      };
    case "module_view":
    case "cycle_view":
    case "issue_views_view":
    case "page_view":
    case "intake_view":
      return {
        message: (
          <>
            {getBooleanActionText(newValue)}{" "}
            {
              (
                {
                  module_view: "模块",
                  cycle_view: "周期",
                  issue_views_view: "工作项",
                  page_view: "文档",
                  intake_view: "需求收集",
                } as Record<string, string>
              )[activityType]
            }{" "}
            视图
          </>
        ),
      };
    case "is_project_updates_enabled":
      return {
        message: <>{getBooleanActionText(newValue)} 项目动态</>,
      };
    case "is_epic_enabled":
      return {
        message: <>{getBooleanActionText(newValue)} 史诗</>,
      };
    case "is_workflow_enabled":
      return {
        message: <>{getBooleanActionText(newValue)} 自定义工作流</>,
      };
    case "is_time_tracking_enabled":
      return {
        message: <>{getBooleanActionText(newValue)} 工时跟踪</>,
      };
    case "is_issue_type_enabled":
      return {
        message: <>{getBooleanActionText(newValue)} 工作项类型</>,
      };
    default:
      return {
        message: `${verb} ${activityType?.replace(/_/g, " ")} `,
      };
  }
};
