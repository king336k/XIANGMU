/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { EAuthModes } from "@plane/constants";

interface TermsAndConditionsProps {
  authType?: EAuthModes;
}

export function TermsAndConditions(_props: TermsAndConditionsProps) {
  return <p className="text-center text-13 text-tertiary">部署使用请遵循本单位账号与数据管理要求。</p>;
}
