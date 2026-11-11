/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { GOD_MODE_URL } from "@plane/constants";
import DefaultLayout from "@/layouts/default-layout";
import { PlatformLogo } from "@/components/common/platform-logo";
import { Button } from "@plane/propel/button";

export function InstanceNotReady() {
  return (
    <DefaultLayout>
      <div className="relative z-10 flex h-screen w-screen overflow-hidden">
        {/* Main content */}
        <div className="flex h-full w-full flex-col items-center px-8 pt-6 pb-10">
          <div className="sticky top-0 flex w-full shrink-0 items-center justify-between gap-6">
            <PlatformLogo />
          </div>
          <div className="flex h-full w-full flex-col items-center justify-center gap-7">
            <div className="flex flex-col items-center gap-11">
              <PlatformLogo className="h-20 w-auto max-w-full" />
              <div className="flex max-w-124 flex-col items-center gap-3">
                <h1 className="text-h2-semibold text-primary">初始化项目管理平台</h1>
                <p className="text-center text-body-md-regular text-secondary">
                  完成实例设置并创建工作空间，即可管理项目、需求、缺陷和测试。
                </p>
              </div>
            </div>
            <a href={GOD_MODE_URL} className="w-72">
              <Button variant="primary" className="w-full" size="xl">
                开始设置
              </Button>
            </a>
          </div>
        </div>
      </div>
    </DefaultLayout>
  );
}
