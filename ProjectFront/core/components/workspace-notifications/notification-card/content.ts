/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TNotificationContentMap } from "@/components/workspace-notifications/sidebar/notification-card/content";

// Additional notification content map for CE (empty - EE extends this)
export const ADDITIONAL_NOTIFICATION_CONTENT_MAP: TNotificationContentMap = {};

// Fallback action renderer for fields not in the map
export const renderAdditionalAction = (notificationField: string, verb: string | undefined) => {
  const baseAction = !["comment", "archived_at"].includes(notificationField) ? verb : "";
  const verbs: Record<string, string> = { created: "新建", updated: "更新", deleted: "删除" };
  const fields: Record<string, string> = {
    state: "状态",
    status: "处理状态",
    priority: "优先级",
    name: "标题",
    description: "描述",
    attachment: "附件",
    link: "链接",
    cycle: "周期",
    module: "模块",
    estimate: "预估",
    estimate_point: "预估",
    completed_at: "完成时间",
    issue: "工作项",
  };
  return `${verbs[baseAction || ""] || "更新"}${fields[notificationField] || "工作项"}`;
};

// Fallback value renderer for fields not in the map
export const renderAdditionalValue = (
  _notificationField: string | undefined,
  newValue: string | undefined,
  _oldValue: string | undefined
) =>
  ["state", "status"].includes(_notificationField || "")
    ? (
        {
          pending_tech: "待技术确认",
          needs_tech: "待技术处理",
          open: "待处理",
          in_progress: "处理中",
          resolved: "已修复，待回归",
          closed: "已关闭",
        } as Record<string, string>
      )[newValue || ""] || newValue
    : _notificationField === "priority"
      ? ({ urgent: "紧急", high: "高", medium: "中", low: "低", none: "未设置" } as Record<string, string>)[
          newValue || "none"
        ] || newValue
      : newValue;

export const shouldShowConnector = (notificationField: string | undefined) =>
  !["comment", "archived_at", "None", "assignees", "labels", "start_date", "target_date", "parent"].includes(
    notificationField || ""
  );

export const shouldRender = (notificationField: string | undefined, verb: string | undefined) => verb !== "deleted";
