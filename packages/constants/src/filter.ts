/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export enum E_SORT_ORDER {
  ASC = "asc",
  DESC = "desc",
}
export const DATE_AFTER_FILTER_OPTIONS = [
  {
    name: "1 周后",
    value: "1_weeks;after;fromnow",
  },
  {
    name: "2 周后",
    value: "2_weeks;after;fromnow",
  },
  {
    name: "1 个月后",
    value: "1_months;after;fromnow",
  },
  {
    name: "2 个月后",
    value: "2_months;after;fromnow",
  },
];

export const DATE_BEFORE_FILTER_OPTIONS = [
  {
    name: "1周前",
    value: "1_weeks;before;fromnow",
  },
  {
    name: "2周前",
    value: "2_weeks;before;fromnow",
  },
  {
    name: "1个月前",
    i18n_name: "date_filters.1_month_ago",
    value: "1_months;before;fromnow",
  },
];

export const PROJECT_CREATED_AT_FILTER_OPTIONS = [
  {
    name: "今天",
    value: "today;custom;custom",
  },
  {
    name: "昨天",
    value: "yesterday;custom;custom",
  },
  {
    name: "最近7天",
    value: "last_7_days;custom;custom",
  },
  {
    name: "最近30天",
    value: "last_30_days;custom;custom",
  },
];
