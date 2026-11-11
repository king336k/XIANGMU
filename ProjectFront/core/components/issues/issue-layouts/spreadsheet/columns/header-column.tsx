/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ArrowDownWideNarrow, ArrowUpNarrowWide, CheckIcon, ChevronDownIcon, Eraser, MoveRight } from "lucide-react";
import { SPREADSHEET_PROPERTY_DETAILS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
import { CustomMenu, Row } from "@plane/ui";
import { SpreadSheetPropertyIcon } from "../../utils";
import {
  getSpreadsheetSortField,
  getSpreadsheetSorts,
  moveSpreadsheetColumnSort,
  updateSpreadsheetColumnSort,
} from "../spreadsheet-column-filter.helper";

interface Props {
  property: keyof IIssueDisplayProperties;
  displayFilters: IIssueDisplayFilterOptions;
  handleDisplayFilterUpdate: (data: Partial<IIssueDisplayFilterOptions>) => void;
  onClose: () => void;
  isEpic?: boolean;
}

export function HeaderColumn(props: Props) {
  const { displayFilters, handleDisplayFilterUpdate, property, onClose, isEpic = false } = props;
  const { t } = useTranslation();
  const propertyDetails = SPREADSHEET_PROPERTY_DETAILS[property];
  if (!propertyDetails) return null;
  const field = getSpreadsheetSortField(propertyDetails.ascendingOrderKey);
  const sorts = getSpreadsheetSorts(displayFilters.order_by);
  const sortIndex = sorts.findIndex((sort) => getSpreadsheetSortField(sort) === field);
  const activeSort = sorts[sortIndex];
  const supportsServerSort = !["link", "attachment_count", "sub_issue_count"].includes(property);
  const canAddSort = supportsServerSort && (sortIndex >= 0 || sorts.length < 5);
  const labels: Record<string, string> = {
    New: "新",
    Old: "旧",
    Low: "低",
    High: "高",
    None: "无",
    Urgent: "紧急",
    Most: "多",
    Least: "少",
  };
  const setOrder = (order?: string) =>
    handleDisplayFilterUpdate({ order_by: updateSpreadsheetColumnSort(displayFilters.order_by, field, order) });
  return (
    <CustomMenu
      customButtonClassName="clickable !w-full"
      customButtonTabIndex={-1}
      className="!w-full"
      customButton={
        <Row className="flex w-full cursor-pointer items-center justify-between gap-1.5 py-2 text-13 text-secondary hover:text-primary">
          <div className="flex items-center gap-1.5">
            <SpreadSheetPropertyIcon iconKey={propertyDetails.icon} className="h-4 w-4 text-placeholder" />
            {property === "sub_issue_count" && isEpic ? t("issue.label", { count: 2 }) : t(propertyDetails.i18n_title)}
          </div>
          <div className="ml-1 flex items-center gap-0.5">
            {sortIndex >= 0 && (
              <>
                <span className="text-10 text-accent-primary" title={`第${sortIndex + 1}排序条件`}>
                  {sortIndex + 1}
                </span>
                {activeSort.startsWith("-") ? (
                  <ArrowUpNarrowWide className="h-3 w-3" />
                ) : (
                  <ArrowDownWideNarrow className="h-3 w-3" />
                )}
              </>
            )}
            <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
          </div>
        </Row>
      }
      onMenuClose={onClose}
      placement="bottom-start"
      closeOnSelect
    >
      <div className="px-2 py-1 text-11 text-tertiary">
        {!supportsServerSort
          ? "此列暂不支持服务端组合排序"
          : sortIndex >= 0
            ? `第${sortIndex + 1}排序条件`
            : canAddSort
              ? "添加为下一排序条件"
              : "最多组合5列排序"}
      </div>
      {[
        {
          order: propertyDetails.ascendingOrderKey,
          from: propertyDetails.ascendingOrderTitle,
          to: propertyDetails.descendingOrderTitle,
          icon: ArrowDownWideNarrow,
        },
        {
          order: propertyDetails.descendingOrderKey,
          from: propertyDetails.descendingOrderTitle,
          to: propertyDetails.ascendingOrderTitle,
          icon: ArrowUpNarrowWide,
        },
      ].map(({ order, from, to, icon: Icon }) => (
        <CustomMenu.MenuItem key={order} disabled={!canAddSort} onClick={() => setOrder(order)}>
          <div className="flex items-center justify-between gap-3 px-1">
            <div className="flex items-center gap-2">
              <Icon className="size-3" />
              {from === "A" || from === "Z" ? (
                <span>{from === "A" ? "名称顺序" : "名称倒序"}</span>
              ) : from === "New" || from === "Old" ? (
                <span>{from === "New" ? "较新在前" : "较早在前"}</span>
              ) : (
                <>
                  <span>{labels[from] ?? from}</span>
                  <MoveRight className="size-3" />
                  <span>{labels[to] ?? to}</span>
                </>
              )}
            </div>
            {activeSort === order && <CheckIcon className="size-3" />}
          </div>
        </CustomMenu.MenuItem>
      ))}
      {sortIndex > 0 && (
        <CustomMenu.MenuItem
          onClick={() =>
            handleDisplayFilterUpdate({ order_by: moveSpreadsheetColumnSort(displayFilters.order_by, field, -1) })
          }
        >
          提高排序优先级
        </CustomMenu.MenuItem>
      )}
      {sortIndex >= 0 && sortIndex < sorts.length - 1 && (
        <CustomMenu.MenuItem
          onClick={() =>
            handleDisplayFilterUpdate({ order_by: moveSpreadsheetColumnSort(displayFilters.order_by, field, 1) })
          }
        >
          降低排序优先级
        </CustomMenu.MenuItem>
      )}
      {sortIndex >= 0 && (
        <CustomMenu.MenuItem onClick={() => setOrder()}>
          <div className="flex items-center gap-2 px-1">
            <Eraser className="size-3" />
            <span>清除此列排序</span>
          </div>
        </CustomMenu.MenuItem>
      )}
    </CustomMenu>
  );
}
