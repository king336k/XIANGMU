/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { PlatformLogo } from "./platform-logo";

export function LogoSpinner() {
  return (
    <div className="flex items-center justify-center" role="status" aria-label="正在加载">
      <PlatformLogo compact className="size-10 animate-pulse motion-reduce:animate-none" />
    </div>
  );
}
