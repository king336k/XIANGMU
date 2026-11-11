/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { cn } from "@plane/utils";

type TSidebarNavItem = {
  className?: string;
  isActive?: boolean;
  children?: React.ReactNode;
};

export function SidebarNavItem(props: TSidebarNavItem) {
  const { className, isActive, children } = props;
  return (
    <div
      className={cn(
        "platform-sidebar-item group relative flex min-h-9 w-full cursor-pointer items-center justify-between gap-1.5 rounded-md border border-transparent px-2.5 py-1.5 outline-none",
        {
          "border-accent-subtle bg-accent-subtle text-accent-primary": isActive,
          "text-secondary hover:bg-layer-transparent-hover active:bg-layer-transparent-active": !isActive,
        },
        className
      )}
    >
      {children}
    </div>
  );
}
