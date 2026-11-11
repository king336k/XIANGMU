/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { ContentWrapper } from "@plane/ui";

export function WorkspaceActiveCyclesUpgrade() {
  const { workspaceSlug } = useParams();
  return (
    <ContentWrapper className="p-6">
      <div className="space-y-3 rounded-md border border-subtle p-6">
        <h2 className="text-16 font-semibold">项目周期</h2>
        <p className="text-13 text-secondary">进入具体项目查看迭代周期、工作项和进度。</p>
        <Link href={`/${workspaceSlug}/projects`} className="text-13 text-accent-primary">
          查看项目 →
        </Link>
      </div>
    </ContentWrapper>
  );
}
