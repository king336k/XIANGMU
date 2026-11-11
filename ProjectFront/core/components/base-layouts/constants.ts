/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { BoardLayoutIcon, ListLayoutIcon, TimelineLayoutIcon } from "@plane/propel/icons";
import type { IBaseLayoutConfig } from "@plane/types";

export const BASE_LAYOUTS: IBaseLayoutConfig[] = [
  {
    key: "list",
    icon: ListLayoutIcon,
    label: "列表布局",
  },
  {
    key: "kanban",
    icon: BoardLayoutIcon,
    label: "看板布局",
  },
  {
    key: "gantt",
    icon: TimelineLayoutIcon,
    label: "甘特图布局",
  },
];
