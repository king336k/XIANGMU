/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { cn, getFileURL } from "@plane/utils";
import { Building2 } from "lucide-react";

type Props = {
  logo: string | null | undefined;
  name: string | undefined;
  classNames?: string;
};

export const WorkspaceLogo = observer(function WorkspaceLogo(props: Props) {
  // translation
  const { t } = useTranslation();

  return (
    <div
      className={cn(
        `relative grid h-6 w-6 flex-shrink-0 place-items-center ${
          !props.logo && "rounded-md border border-subtle bg-layer-1 text-accent-primary"
        } ${props.classNames ? props.classNames : ""}`
      )}
    >
      {props.logo && props.logo !== "" ? (
        <img
          src={getFileURL(props.logo)}
          className="absolute top-0 left-0 h-full w-full rounded-md object-cover"
          alt={t("aria_labels.projects_sidebar.workspace_logo")}
        />
      ) : (
        <Building2 className="size-4" role="img" aria-label="工作空间" focusable="false" />
      )}
    </div>
  );
});
