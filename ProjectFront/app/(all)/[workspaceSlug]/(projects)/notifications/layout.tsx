/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Outlet } from "react-router";
// components

export default function ProjectInboxIssuesLayout() {
  return (
    <div className="h-full min-w-0 overflow-hidden">
      <Outlet />
    </div>
  );
}
