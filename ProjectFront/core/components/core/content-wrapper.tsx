/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
// helpers
import { cn } from "@plane/utils";

export interface ContentWrapperProps {
  className?: string;
  children: ReactNode;
}

export function ContentWrapper({ className, children }: ContentWrapperProps) {
  return (
    <div className="min-h-0 w-full min-w-0 flex-1 overflow-hidden">
      <div
        className={cn(
          "platform-content relative h-full min-h-0 w-full min-w-0 overflow-x-hidden overflow-y-auto",
          className
        )}
      >
        {children}
      </div>
    </div>
  );
}
