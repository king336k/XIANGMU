/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// types
import type { WeekMonthDataType, ChartDataType, TGanttViews } from "@plane/types";
import { EStartOfTheWeek } from "@plane/types";

// constants
export const generateWeeks = (startOfWeek: EStartOfTheWeek = EStartOfTheWeek.SUNDAY): WeekMonthDataType[] => [
  ...weeks.slice(startOfWeek),
  ...weeks.slice(0, startOfWeek),
];

export const weeks: WeekMonthDataType[] = [
  { key: 0, shortTitle: "sun", title: "星期日", abbreviation: "Su" },
  { key: 1, shortTitle: "mon", title: "星期一", abbreviation: "M" },
  { key: 2, shortTitle: "tue", title: "星期二", abbreviation: "T" },
  { key: 3, shortTitle: "wed", title: "星期三", abbreviation: "W" },
  { key: 4, shortTitle: "thurs", title: "星期四", abbreviation: "Th" },
  { key: 5, shortTitle: "fri", title: "星期五", abbreviation: "F" },
  { key: 6, shortTitle: "sat", title: "星期六", abbreviation: "Sa" },
];

export const months: WeekMonthDataType[] = [
  { key: 0, shortTitle: "jan", title: "1月", abbreviation: "Jan" },
  { key: 1, shortTitle: "feb", title: "2月", abbreviation: "Feb" },
  { key: 2, shortTitle: "mar", title: "3月", abbreviation: "Mar" },
  { key: 3, shortTitle: "apr", title: "4月", abbreviation: "Apr" },
  { key: 4, shortTitle: "may", title: "5月", abbreviation: "May" },
  { key: 5, shortTitle: "jun", title: "6月", abbreviation: "Jun" },
  { key: 6, shortTitle: "jul", title: "7月", abbreviation: "Jul" },
  { key: 7, shortTitle: "aug", title: "8月", abbreviation: "Aug" },
  { key: 8, shortTitle: "sept", title: "9月", abbreviation: "Sept" },
  { key: 9, shortTitle: "oct", title: "10月", abbreviation: "Oct" },
  { key: 10, shortTitle: "nov", title: "11月", abbreviation: "Nov" },
  { key: 11, shortTitle: "dec", title: "12月", abbreviation: "Dec" },
];

export const quarters: WeekMonthDataType[] = [
  { key: 0, shortTitle: "Q1", title: "1–3月", abbreviation: "Q1" },
  { key: 1, shortTitle: "Q2", title: "4–6月", abbreviation: "Q2" },
  { key: 2, shortTitle: "Q3", title: "7–9月", abbreviation: "Q3" },
  { key: 3, shortTitle: "Q4", title: "10–12月", abbreviation: "Q4" },
];

export const charCapitalize = (word: string) => `${word.charAt(0).toUpperCase()}${word.substring(1)}`;

export const bindZero = (value: number) => (value > 9 ? `${value}` : `0${value}`);

export const timePreview = (date: Date) => `${bindZero(date.getHours())}:${bindZero(date.getMinutes())}`;

export const datePreview = (date: Date, includeTime: boolean = false) =>
  `${date.getFullYear()}/${bindZero(date.getMonth() + 1)}/${bindZero(date.getDate())}${includeTime ? ` ${timePreview(date)}` : ""}`;

// context data
export const VIEWS_LIST: ChartDataType[] = [
  {
    key: "week",
    i18n_title: "common.week",
    data: {
      startDate: new Date(),
      currentDate: new Date(),
      endDate: new Date(),
      approxFilterRange: 4, // it will preview week dates with weekends highlighted with 1 week limitations ex: title (Wed 1, Thu 2, Fri 3)
      dayWidth: 60,
    },
  },
  {
    key: "month",
    i18n_title: "common.month",
    data: {
      startDate: new Date(),
      currentDate: new Date(),
      endDate: new Date(),
      approxFilterRange: 6, // it will preview monthly all dates with weekends highlighted with no limitations ex: title (1, 2, 3)
      dayWidth: 20,
    },
  },
  {
    key: "quarter",
    i18n_title: "common.quarter",
    data: {
      startDate: new Date(),
      currentDate: new Date(),
      endDate: new Date(),
      approxFilterRange: 24, // it will preview week starting dates all months data and there is 3 months limitation for preview ex: title (2, 9, 16, 23, 30)
      dayWidth: 5,
    },
  },
];

export const currentViewDataWithView = (view: TGanttViews = "month") =>
  VIEWS_LIST.find((_viewData) => _viewData.key === view);
