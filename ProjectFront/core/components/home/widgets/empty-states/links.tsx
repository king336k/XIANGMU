/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import { EmptyStateCompact } from "@plane/propel/empty-state";

export function LinksEmptyState() {
  const { t } = useTranslation();
  return (
    <div className="flex w-full items-center justify-center rounded-md border border-dashed border-subtle bg-layer-1 px-4 py-3">
      <EmptyStateCompact
        assetKey="link"
        assetClassName="hidden"
        title={t("workspace_empty_state.home_widget_quick_links.title")}
      />
    </div>
  );
}
