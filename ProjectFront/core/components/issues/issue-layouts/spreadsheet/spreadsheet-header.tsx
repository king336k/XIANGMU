/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Filter } from "lucide-react";
import { EIssuesStoreType } from "@plane/types";
import { useIssueStoreType, useIssuesStore } from "@/hooks/use-issue-layout-store";
import { useWorkItemFilterInstance } from "@/hooks/store/work-item-filters/use-work-item-filter-instance";
import { useParams } from "next/navigation";
// constants
import { SPREADSHEET_SELECT_GROUP } from "@plane/constants";
// ui
import type { IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
// components
import { cn } from "@plane/utils";
import { MultipleSelectGroupAction } from "@/components/core/multiple-select";
// hooks
import type { TSelectionHelper } from "@/hooks/use-multiple-select";
import { isSpreadsheetFilterExpressionEditable } from "./spreadsheet-column-filter.helper";
import { SpreadsheetHeaderColumn } from "./spreadsheet-header-column";

interface Props {
  displayProperties: IIssueDisplayProperties;
  displayFilters: IIssueDisplayFilterOptions;
  handleDisplayFilterUpdate: (data: Partial<IIssueDisplayFilterOptions>) => void;
  canEditProperties: (projectId: string | undefined, issueId?: string) => boolean;
  isEstimateEnabled: boolean;
  spreadsheetColumnsList: (keyof IIssueDisplayProperties)[];
  selectionHelpers: TSelectionHelper;
  isEpic?: boolean;
}

export const SpreadsheetHeader = observer(function SpreadsheetHeader(props: Props) {
  const {
    displayProperties,
    displayFilters,
    handleDisplayFilterUpdate,
    canEditProperties,
    isEstimateEnabled,
    spreadsheetColumnsList,
    selectionHelpers,
    isEpic = false,
  } = props;
  // router
  const { projectId, cycleId, moduleId, viewId, globalViewId, userId, workspaceSlug } = useParams();
  const storeType = useIssueStoreType();
  const { issuesFilter } = useIssuesStore();
  const entityId =
    storeType === EIssuesStoreType.CYCLE
      ? cycleId
      : storeType === EIssuesStoreType.MODULE
        ? moduleId
        : storeType === EIssuesStoreType.GLOBAL
          ? globalViewId
          : storeType === EIssuesStoreType.PROJECT_VIEW
            ? viewId
            : storeType === EIssuesStoreType.PROFILE
              ? userId
              : storeType === EIssuesStoreType.WORKSPACE_DRAFT
                ? workspaceSlug
                : projectId;
  const filter = useWorkItemFilterInstance(storeType, entityId?.toString());
  // The native adapter only supports AND groups. Never overwrite an unrepresentable saved expression.
  const canEditColumnFilters = isSpreadsheetFilterExpressionEditable(filter, issuesFilter.issueFilters?.richFilters);
  // derived values
  const isGroupSelectionEmpty = selectionHelpers.isGroupSelected(SPREADSHEET_SELECT_GROUP) === "empty";
  // auth
  const canSelectIssues = canEditProperties(projectId?.toString()) && !selectionHelpers.isSelectionDisabled;

  return (
    <thead className="sticky top-0 left-0 z-[12] border-b-[0.5px] border-subtle">
      <tr>
        {/* Single header column containing both identifier and workitem */}
        <th
          className="group/list-header left-0 z-[15] h-11 w-96 max-w-lg min-w-80 border-r-[0.5px] border-subtle bg-layer-1 text-13 font-medium md:sticky"
          tabIndex={-1}
        >
          <div className="flex h-full w-full items-center gap-2 px-page-x">
            {/* Workitem header section */}
            <div className="flex h-full min-w-0 flex-grow items-center gap-1 py-2.5">
              {canSelectIssues && (
                <div className="mr-1 flex w-3.5 flex-shrink-0 items-center">
                  <MultipleSelectGroupAction
                    className={cn(
                      "pointer-events-none size-3.5 opacity-0 !outline-none group-hover/list-header:pointer-events-auto group-hover/list-header:opacity-100",
                      {
                        "pointer-events-auto opacity-100": !isGroupSelectionEmpty,
                      }
                    )}
                    groupID={SPREADSHEET_SELECT_GROUP}
                    selectionHelpers={selectionHelpers}
                  />
                </div>
              )}
              <span className="text-13 font-medium">{`${isEpic ? "史诗需求" : "工作项"}`}</span>
              {filter && (
                <button
                  type="button"
                  className="rounded p-1 text-tertiary hover:bg-layer-2"
                  aria-label="筛选工作项"
                  title={
                    canEditColumnFilters ? "按状态、优先级、负责人等条件筛选工作项" : "当前组合筛选请使用上方筛选器"
                  }
                  onClick={() => filter.toggleVisibility(true)}
                >
                  <Filter className="size-3.5" />
                </button>
              )}
              <span className="font-normal ml-auto hidden text-11 text-tertiary xl:block">向右滚动查看更多</span>
            </div>
          </div>
        </th>

        {spreadsheetColumnsList.map((property) => (
          <SpreadsheetHeaderColumn
            key={property}
            property={property}
            filter={canEditColumnFilters ? filter : undefined}
            displayProperties={displayProperties}
            displayFilters={displayFilters}
            handleDisplayFilterUpdate={handleDisplayFilterUpdate}
            isEstimateEnabled={isEstimateEnabled}
            isEpic={isEpic}
          />
        ))}
      </tr>
    </thead>
  );
});
