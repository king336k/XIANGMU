import { PlatformLogo } from "@/components/common/platform-logo";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { Button } from "@plane/propel/button";
// assets
// layouts
import DefaultLayout from "@/layouts/default-layout";

// Production Error Component
interface ProdErrorComponentProps {
  onGoHome: () => void;
}

export function ProdErrorComponent({ onGoHome }: ProdErrorComponentProps) {
  // hooks

  // derived values

  return (
    <DefaultLayout>
      <div className="relative container mx-auto flex h-full w-full max-w-xl flex-col items-center justify-center gap-2 gap-y-6 bg-surface-1 px-6 text-center">
        <div className="relative w-full">
          <PlatformLogo compact className="mx-auto size-16" />
        </div>
        <div className="relative mt-4 flex w-full flex-col gap-4">
          <div className="flex flex-col gap-2.5">
            <h1 className="text-left text-18 font-semibold text-primary">页面暂时无法显示</h1>
            <span className="text-left text-14 font-medium text-secondary">
              请先刷新页面，或返回首页重试。如仍无法访问，请联系管理员，并说明发生问题的页面和时间。
            </span>
          </div>

          <div className="flex items-center justify-start gap-6">
            <Button variant="primary" size="lg" onClick={onGoHome}>
              返回首页
            </Button>
          </div>
        </div>
      </div>
    </DefaultLayout>
  );
}
