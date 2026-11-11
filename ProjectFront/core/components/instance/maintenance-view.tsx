import { PlatformLogo } from "@/components/common/platform-logo";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// assets
// layouts
import DefaultLayout from "@/layouts/default-layout";
// components
import { MaintenanceMessage } from "./maintenance-message";

export function MaintenanceView() {
  // hooks
  // derived values
  return (
    <DefaultLayout>
      <div className="relative container mx-auto flex h-full w-full max-w-xl flex-col items-center justify-center gap-2 gap-y-6 bg-surface-1 text-center">
        <div className="relative w-full">
          <PlatformLogo compact className="mx-auto size-16" />
        </div>
        <div className="relative mt-4 flex w-full flex-col gap-4">
          <MaintenanceMessage />
        </div>
      </div>
    </DefaultLayout>
  );
}
