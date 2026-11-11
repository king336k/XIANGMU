/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useEffect, useRef } from "react";
import { observer } from "mobx-react";
// plane constants
import { SPREADSHEET_SELECT_GROUP, SPREADSHEET_PROPERTY_LIST } from "@plane/constants";
// types
import type { TIssue, IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
import { EIssueLayoutTypes } from "@plane/types";
// components
import { MultipleSelectGroup } from "@/components/core/multiple-select";
import { IssueBulkOperationsRoot } from "@/components/issues/bulk-operations";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useBulkOperationStatus } from "@/hooks/use-bulk-operation-status";
// local imports
import type { TRenderQuickActions } from "../list/list-view-types";
import { QuickAddIssueRoot, SpreadsheetAddIssueButton } from "../quick-add";
import { SpreadsheetTable } from "./spreadsheet-table";
import { useSpreadsheetPagination } from "./use-pagination";
import { SPREADSHEET_PAGE_SIZES } from "./pagination";
import { Paging } from "@/components/quality/shared";
import type { TSelectionHelper } from "@/hooks/use-multiple-select";

type Props = {
  displayProperties: IIssueDisplayProperties;
  displayFilters: IIssueDisplayFilterOptions;
  handleDisplayFilterUpdate: (data: Partial<IIssueDisplayFilterOptions>) => void;
  issueIds: string[] | undefined;
  totalIssueCount?: number;
  quickActions: TRenderQuickActions;
  updateIssue: ((projectId: string | null, issueId: string, data: Partial<TIssue>) => Promise<void>) | undefined;
  openIssuesListModal?: (() => void) | null;
  quickAddCallback?: (projectId: string | null | undefined, data: TIssue) => Promise<TIssue | undefined>;
  canEditProperties: (projectId: string | undefined, issueId?: string) => boolean;
  canLoadMoreIssues: boolean;
  loadMoreIssues: () => void;
  enableQuickCreateIssue?: boolean;
  disableIssueCreation?: boolean;
  isWorkspaceLevel?: boolean;
  isEpic?: boolean;
};

export const SpreadsheetView = observer(function SpreadsheetView(props: Props) {
  const {
    displayProperties,
    displayFilters,
    handleDisplayFilterUpdate,
    issueIds,
    totalIssueCount,
    quickActions,
    updateIssue,
    quickAddCallback,
    canEditProperties,
    enableQuickCreateIssue,
    disableIssueCreation,
    isWorkspaceLevel = false,
    isEpic = false,
  } = props;
  // refs
  const containerRef = useRef<HTMLTableElement | null>(null);
  const portalRef = useRef<HTMLDivElement | null>(null);
  const pagination = useSpreadsheetPagination(issueIds ?? [], displayFilters.order_by, totalIssueCount);
  // store hooks
  const { currentProjectDetails } = useProject();
  // plane web hooks
  const isBulkOperationsEnabled = useBulkOperationStatus();

  const isEstimateEnabled: boolean = currentProjectDetails?.estimate !== null;

  const visibleColumns = isWorkspaceLevel
    ? SPREADSHEET_PROPERTY_LIST
    : SPREADSHEET_PROPERTY_LIST.filter((property) => {
        if (property === "cycle" && !currentProjectDetails?.cycle_view) return false;
        if (property === "modules" && !currentProjectDetails?.module_view) return false;
        return true;
      });

  const spreadsheetColumnsList = [
    ...visibleColumns.filter((property) => property === "state" || property === "assignee"),
    ...visibleColumns.filter((property) => property !== "state" && property !== "assignee"),
  ];

  if (!issueIds || issueIds.length === 0) return <></>;
  return (
    <div
      data-work-item-spreadsheet
      data-total-count={pagination.total}
      data-visible-count={pagination.visibleIds.length}
      data-page={pagination.page}
      data-page-size={pagination.pageSize}
      className="relative flex h-full w-full flex-col overflow-x-hidden bg-layer-1 whitespace-nowrap text-secondary"
    >
      <div ref={portalRef} className="spreadsheet-menu-portal" />
      <MultipleSelectGroup
        containerRef={containerRef}
        entities={{
          [SPREADSHEET_SELECT_GROUP]: pagination.visibleIds,
        }}
        disabled={!isBulkOperationsEnabled || isEpic}
      >
        {(helpers) => (
          <>
            <ClearSpreadsheetSelection scope={pagination.selectionScope} clear={helpers.handleClearSelection} />
            <div
              ref={containerRef}
              className="vertical-scrollbar horizontal-scrollbar scrollbar-lg min-h-0 w-full flex-1 overflow-auto"
              role="region"
              aria-label="工作项表格，可横向滚动查看全部字段"
              tabIndex={0}
            >
              <SpreadsheetTable
                displayProperties={displayProperties}
                displayFilters={displayFilters}
                handleDisplayFilterUpdate={handleDisplayFilterUpdate}
                issueIds={pagination.visibleIds}
                isEstimateEnabled={isEstimateEnabled}
                portalElement={portalRef}
                quickActions={quickActions}
                updateIssue={updateIssue}
                canEditProperties={canEditProperties}
                containerRef={containerRef}
                spreadsheetColumnsList={spreadsheetColumnsList}
                selectionHelpers={helpers}
                isEpic={isEpic}
              />
            </div>
            <fieldset disabled={pagination.busy} className="shrink-0 border-0 px-3">
              <legend className="sr-only">工作项表格分页</legend>
              {pagination.error && (
                <p role="alert" className="text-12 text-danger-primary">
                  加载失败，当前页已保留。
                  <button type="button" className="ml-2 underline" onClick={() => void pagination.onRetry()}>
                    重试
                  </button>
                </p>
              )}
              {pagination.busy && (
                <span role="status" className="text-12">
                  加载中…
                </span>
              )}
              <Paging
                page={pagination.page}
                count={pagination.total}
                perPage={pagination.pageSize}
                pageSizes={SPREADSHEET_PAGE_SIZES}
                onChange={(page) => void pagination.onPage(page)}
                onPageSizeChange={pagination.onPageSizeChange}
              />
            </fieldset>
            <div className="border-t border-subtle">
              <div className="sticky bottom-0 left-0 z-5">
                {enableQuickCreateIssue && !disableIssueCreation && (
                  <QuickAddIssueRoot
                    layout={EIssueLayoutTypes.SPREADSHEET}
                    QuickAddButton={SpreadsheetAddIssueButton}
                    quickAddCallback={quickAddCallback}
                    isEpic={isEpic}
                  />
                )}
              </div>
            </div>
            <IssueBulkOperationsRoot selectionHelpers={helpers} />
          </>
        )}
      </MultipleSelectGroup>
    </div>
  );
});

function ClearSpreadsheetSelection({
  scope,
  clear,
}: {
  scope: string;
  clear: TSelectionHelper["handleClearSelection"];
}) {
  useEffect(() => clear(), [scope, clear]);
  return null;
}
