/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// assets
import { useTranslation } from "@plane/i18n";
import packageJson from "package.json";

export function PlaneVersionNumber() {
  const { t } = useTranslation();
  return (
    <span className="flex flex-col gap-1">
      <span>
        {t("version")}: v{packageJson.version}
      </span>
      <a
        href="https://github.com/makeplane/plane/blob/preview/LICENSE"
        target="_blank"
        rel="noopener noreferrer"
        className="hover:underline"
      >
        开源组件 Plane · AGPL-3.0
      </a>
    </span>
  );
}
