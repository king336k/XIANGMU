/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TAnalyticsTabsBase } from "@plane/types";
import { ChartXAxisProperty, ChartYAxisMetric } from "@plane/types";

export interface IInsightField {
  key: string;
  i18nKey: string;
  i18nProps?: {
    entity?: string;
    entityPlural?: string;
    prefix?: string;
    suffix?: string;
    [key: string]: unknown;
  };
}

export const ANALYTICS_INSIGHTS_FIELDS: Record<TAnalyticsTabsBase, IInsightField[]> = {
  overview: [
    {
      key: "total_users",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.users",
      },
    },
    {
      key: "total_admins",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.admins",
      },
    },
    {
      key: "total_members",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.members",
      },
    },
    {
      key: "total_guests",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.guests",
      },
    },
    {
      key: "total_projects",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.projects",
      },
    },
    {
      key: "total_work_items",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.work_items",
      },
    },
    {
      key: "total_cycles",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "common.cycles",
      },
    },
    {
      key: "total_intake",
      i18nKey: "workspace_analytics.total",
      i18nProps: {
        entity: "sidebar.intake",
      },
    },
  ],
  "work-items": [
    {
      key: "total_work_items",
      i18nKey: "workspace_analytics.total",
    },
    {
      key: "started_work_items",
      i18nKey: "workspace_analytics.started_work_items",
    },
    {
      key: "backlog_work_items",
      i18nKey: "workspace_analytics.backlog_work_items",
    },
    {
      key: "un_started_work_items",
      i18nKey: "workspace_analytics.un_started_work_items",
    },
    {
      key: "completed_work_items",
      i18nKey: "workspace_analytics.completed_work_items",
    },
  ],
};

export const ANALYTICS_DURATION_FILTER_OPTIONS = [
  {
    name: "昨天",
    value: "yesterday",
  },
  {
    name: "最近7天",
    value: "last_7_days",
  },
  {
    name: "最近30天",
    value: "last_30_days",
  },
  {
    name: "最近3个月",
    value: "last_3_months",
  },
];

export const ANALYTICS_X_AXIS_VALUES: { value: ChartXAxisProperty; label: string }[] = [
  {
    value: ChartXAxisProperty.STATES,
    label: "状态名称",
  },
  {
    value: ChartXAxisProperty.STATE_GROUPS,
    label: "状态分组",
  },
  {
    value: ChartXAxisProperty.PRIORITY,
    label: "优先级",
  },
  {
    value: ChartXAxisProperty.LABELS,
    label: "标签",
  },
  {
    value: ChartXAxisProperty.ASSIGNEES,
    label: "负责人",
  },
  {
    value: ChartXAxisProperty.ESTIMATE_POINTS,
    label: "预估点数",
  },
  {
    value: ChartXAxisProperty.CYCLES,
    label: "周期",
  },
  {
    value: ChartXAxisProperty.MODULES,
    label: "模块",
  },
  {
    value: ChartXAxisProperty.COMPLETED_AT,
    label: "完成日期",
  },
  {
    value: ChartXAxisProperty.TARGET_DATE,
    label: "截止日期",
  },
  {
    value: ChartXAxisProperty.START_DATE,
    label: "开始日期",
  },
  {
    value: ChartXAxisProperty.CREATED_AT,
    label: "创建日期",
  },
];

export const ANALYTICS_Y_AXIS_VALUES: { value: ChartYAxisMetric; label: string }[] = [
  {
    value: ChartYAxisMetric.WORK_ITEM_COUNT,
    label: "工作项",
  },
  {
    value: ChartYAxisMetric.ESTIMATE_POINT_COUNT,
    label: "预估点数",
  },
  {
    value: ChartYAxisMetric.EPIC_WORK_ITEM_COUNT,
    label: "史诗",
  },
];

export const ANALYTICS_V2_DATE_KEYS = ["completed_at", "target_date", "start_date", "created_at"];
