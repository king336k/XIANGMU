// SPDX-License-Identifier: AGPL-3.0-only
import { renderFormattedDate } from "@plane/utils";
export type DefectGroup = { value: string; count: number };
export type DefectStatisticsData = {
  total: number;
  unclosed: number;
  by_status: DefectGroup[];
  by_severity: DefectGroup[];
  opened_by_day: { date: string; count: number }[];
  scope?: string;
  by_category?: DefectGroup[];
  response_pending?: number;
  stage_scope?: string;
  stage_durations?: { key: string; name: string; count: number; average_hours: number | null }[];
};

export function defectReport(data: DefectStatisticsData, now = new Date()) {
  // Match the API's Asia/Shanghai calendar day, independent of the browser timezone.
  const end = Date.parse(`${renderFormattedDate(now, "yyyy-MM-dd")}T00:00:00Z`);
  const counts = new Map(data.opened_by_day.map((row) => [row.date, row.count]));
  const trend = Array.from({ length: 30 }, (_, index) => {
    const date = new Date(end - (29 - index) * 86400000).toISOString().slice(0, 10);
    return { date, name: date.replaceAll("-", "/"), count: counts.get(date) ?? 0 };
  });
  const closed = data.by_status.find((row) => row.value === "closed")?.count ?? 0;
  return {
    trend,
    closed,
    closedPercent: data.total ? Math.round((closed / data.total) * 100) : 0,
    recentTotal: trend.reduce((total, row) => total + row.count, 0),
    awaitingRegression: data.by_status.find((row) => row.value === "resolved")?.count ?? 0,
  };
}
