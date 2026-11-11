/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { AnalyticsTab } from "@plane/types";
import { ProjectPeriodReport } from "./project-period-report";
import { Overview } from "@/components/analytics/overview";
import { WorkItems } from "@/components/analytics/work-items";

type PlatformAnalyticsTab = Omit<AnalyticsTab, "key"> & { key: AnalyticsTab["key"] | "project-report" };

export const getAnalyticsTabs = (t: (key: string, params?: Record<string, any>) => string): PlatformAnalyticsTab[] => [
  { key: "project-report", label: "项目报表", content: ProjectPeriodReport, isDisabled: false },
  { key: "overview", label: t("common.overview"), content: Overview, isDisabled: false },
  { key: "work-items", label: t("work_items"), content: WorkItems, isDisabled: false },
];
