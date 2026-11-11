/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { ScrollArea } from "@plane/propel/scrollarea";
import { cn } from "@plane/utils";
// components
import { AppHeader } from "@/components/core/app-header";

type Props = {
  children: React.ReactNode;
  header?: React.ReactNode;
  hugging?: boolean;
};

export function SettingsContentWrapper(props: Props) {
  const { children, header, hugging = false } = props;

  return (
    <div className="@container flex size-full grow flex-col overflow-hidden">
      {header && (
        <div className="w-full shrink-0">
          <AppHeader header={header} />
        </div>
      )}
      <ScrollArea scrollType="hover" orientation="vertical" size="sm" className="size-full grow overflow-y-scroll">
        <div
          className={cn("py-6", {
            "w-full min-w-0 px-4 sm:px-6 xl:px-8": hugging,
            "w-full max-w-[1280px] min-w-0 px-4 sm:px-6 xl:px-8": !hugging, // 58.95rem = max-width(56.25rem) + padding-x(1.35rem * 2)
          })}
        >
          {children}
        </div>
      </ScrollArea>
    </div>
  );
}
