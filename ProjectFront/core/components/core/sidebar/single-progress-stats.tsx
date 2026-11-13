/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";

type TSingleProgressStatsProps = {
  title: any;
  completed: number;
  total: number;
  onClick?: () => void;
  selected?: boolean;
  unit?: string;
};

export function SingleProgressStats({
  title,
  completed,
  total,
  onClick,
  selected = false,
  unit = "",
}: TSingleProgressStatsProps) {
  const Element = onClick ? "button" : "div";
  return (
    <Element
      type={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(event) => {
        if (onClick && ["Enter", " "].includes(event.key)) {
          event.preventDefault();
          onClick();
        }
      }}
      className={`flex w-full items-center justify-between gap-4 rounded-xs p-1 text-11 ${
        onClick ? "cursor-pointer hover:bg-surface-2" : ""
      } ${selected ? "bg-layer-1" : ""}`}
      onClick={onClick}
    >
      <div className="min-w-0 flex-1 truncate">{title}</div>
      <div className="flex shrink-0 items-center justify-end gap-1 px-2 whitespace-nowrap">
        <div className="flex h-5 items-center justify-center gap-1">
          <span className="w-8 text-right">
            {isNaN(Math.round((completed / total) * 100)) ? "0" : Math.round((completed / total) * 100)}%
          </span>
        </div>
        <span className="text-success-primary">
          完成 {completed}
          {unit}
        </span>
        <span>
          共 {total}
          {unit}
        </span>
      </div>
    </Element>
  );
}
