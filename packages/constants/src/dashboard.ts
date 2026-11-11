/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// types
import type { TIssuesListTypes } from "@plane/types";

export enum EDurationFilters {
  NONE = "none",
  TODAY = "today",
  THIS_WEEK = "this_week",
  THIS_MONTH = "this_month",
  THIS_YEAR = "this_year",
  CUSTOM = "custom",
}

// filter duration options
export const DURATION_FILTER_OPTIONS: {
  key: EDurationFilters;
  label: string;
}[] = [
  {
    key: EDurationFilters.NONE,
    label: "全部时间",
  },
  {
    key: EDurationFilters.TODAY,
    label: "今天到期",
  },
  {
    key: EDurationFilters.THIS_WEEK,
    label: "本周到期",
  },
  {
    key: EDurationFilters.THIS_MONTH,
    label: "本月到期",
  },
  {
    key: EDurationFilters.THIS_YEAR,
    label: "今年到期",
  },
  {
    key: EDurationFilters.CUSTOM,
    label: "自定义",
  },
];

// random background colors for project cards
export const PROJECT_BACKGROUND_COLORS = [
  "bg-gray-500/20",
  "bg-success-subtle",
  "bg-danger-subtle",
  "bg-orange-500/20",
  "bg-blue-500/20",
  "bg-yellow-500/20",
  "bg-pink-500/20",
  "bg-purple-500/20",
];

// assigned and created issues widgets tabs list
export const FILTERED_ISSUES_TABS_LIST: {
  key: TIssuesListTypes;
  label: string;
}[] = [
  {
    key: "upcoming",
    label: "即将到期",
  },
  {
    key: "overdue",
    label: "已逾期",
  },
  {
    key: "completed",
    label: "已完成",
  },
];

// assigned and created issues widgets tabs list
export const UNFILTERED_ISSUES_TABS_LIST: {
  key: TIssuesListTypes;
  label: string;
}[] = [
  {
    key: "pending",
    label: "待处理",
  },
  {
    key: "completed",
    label: "已完成",
  },
];

export type TLinkOptions = {
  userId: string | undefined;
};
