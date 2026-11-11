/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { SITE_NAME } from "@plane/constants";

type PageHeadTitleProps = {
  title?: string;
  description?: string;
};

export function PageHead(_props: PageHeadTitleProps) {
  useEffect(() => {
    document.title = SITE_NAME;
  }, []);

  return null;
}
