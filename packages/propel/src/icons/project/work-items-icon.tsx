/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ListChecks } from "lucide-react";

import type { ISvgIcons } from "../type";

export function WorkItemsIcon({ color = "currentColor", width = 16, height = 16, ...rest }: ISvgIcons) {
  return <ListChecks color={color} width={width} height={height} {...rest} />;
}
