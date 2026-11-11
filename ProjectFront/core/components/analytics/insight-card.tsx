/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane package imports
import React from "react";
import type { IAnalyticsResponseFields } from "@plane/types";
import { Loader } from "@plane/ui";

export type InsightCardProps = {
  data?: IAnalyticsResponseFields;
  label: string;
  isLoading?: boolean;
  onClick?: () => void;
};

function InsightCard(props: InsightCardProps) {
  const { data, label, isLoading = false, onClick } = props;
  const count = data?.count ?? 0;

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isLoading || !onClick}
      aria-label={`查看${label}明细，共${count}条`}
      className="focus-visible:outline-accent-primary flex min-w-0 flex-col gap-3 rounded-md border border-subtle bg-surface-1 p-4 text-left hover:bg-layer-1 disabled:cursor-default"
    >
      <div className="text-13 text-tertiary">{label}</div>
      {!isLoading ? (
        <div className="flex flex-col gap-1">
          <div className="text-20 font-bold text-primary">{count}</div>
        </div>
      ) : (
        <Loader.Item height="50px" width="100%" />
      )}
    </button>
  );
}

export default InsightCard;
