/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { MutableRefObject } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { observer } from "mobx-react";
// plane imports
import { DRAG_ALLOWED_GROUPS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type {
  IGroupByColumn,
  TIssueMap,
  TIssueGroupByOptions,
  TIssueOrderByOptions,
  TIssue,
  IIssueDisplayProperties,
  TIssueKanbanFilters,
} from "@plane/types";
import { EIssueLayoutTypes } from "@plane/types";
import { Row } from "@plane/ui";
import { cn } from "@plane/utils";
// components
import { useWorkFlowFDragNDrop } from "@/components/workflow";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { useIssuesStore } from "@/hooks/use-issue-layout-store";
import type { TSelectionHelper } from "@/hooks/use-multiple-select";
// local imports
import { GroupDragOverlay } from "../group-drag-overlay";
import { ListQuickAddIssueButton, QuickAddIssueRoot } from "../quick-add";
import type { GroupDropLocation } from "../utils";
import {
  getDestinationFromDropPayload,
  getIssueBlockId,
  getSourceFromDropPayload,
  highlightIssueOnDrop,
} from "../utils";
import { IssueBlocksList } from "./blocks-list";
import { HeaderGroupByCard } from "./headers/group-by-card";
import type { TRenderQuickActions } from "./list-view-types";
import { ListPagination } from "./pagination-controls";
import { listPageWindow, loadListPage } from "./pagination";

interface Props {
  groupIssueIds: string[] | undefined;
  group: IGroupByColumn;
  issuesMap: TIssueMap;
  group_by: TIssueGroupByOptions | null;
  orderBy: TIssueOrderByOptions | undefined;
  getGroupIndex: (groupId: string | undefined) => number;
  updateIssue: ((projectId: string | null, issueId: string, data: Partial<TIssue>) => Promise<void>) | undefined;
  quickActions: TRenderQuickActions;
  displayProperties: IIssueDisplayProperties | undefined;
  enableIssueQuickAdd: boolean;
  canEditProperties: (projectId: string | undefined, issueId?: string) => boolean;
  containerRef: MutableRefObject<HTMLDivElement | null>;
  quickAddCallback?: ((projectId: string | null | undefined, data: TIssue) => Promise<TIssue | undefined>) | undefined;
  handleOnDrop: (source: GroupDropLocation, destination: GroupDropLocation) => Promise<void>;
  disableIssueCreation?: boolean;
  addIssuesToView?: (issueIds: string[]) => Promise<TIssue>;
  isCompletedCycle?: boolean;
  showEmptyGroup?: boolean;
  loadMoreIssues: (groupId?: string) => Promise<unknown>;
  page: number;
  onPageChange: (page: number) => void;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  selectionHelpers: TSelectionHelper;
  handleCollapsedGroups: (value: string) => void;
  collapsedGroups: TIssueKanbanFilters;
  isEpic?: boolean;
}

export const ListGroup = observer(function ListGroup(props: Props) {
  const {
    groupIssueIds = [],
    group,
    issuesMap,
    group_by,
    orderBy,
    getGroupIndex,
    updateIssue,
    quickActions,
    displayProperties,
    enableIssueQuickAdd,
    canEditProperties,
    containerRef,
    quickAddCallback,
    handleOnDrop,
    disableIssueCreation,
    addIssuesToView,
    isCompletedCycle,
    showEmptyGroup,
    loadMoreIssues,
    page,
    pageSize,
    onPageSizeChange,
    onPageChange,
    selectionHelpers,
    handleCollapsedGroups,
    collapsedGroups,
    isEpic = false,
  } = props;

  const [isDraggingOverColumn, setIsDraggingOverColumn] = useState(false);
  const [dragColumnOrientation, setDragColumnOrientation] = useState<"justify-start" | "justify-end">("justify-start");
  const isExpanded = !collapsedGroups?.group_by.includes(group.id);
  const groupRef = useRef<HTMLDivElement | null>(null);
  const { t } = useTranslation();
  const projectState = useProjectState();

  const {
    issues: { getGroupIssueCount, getPaginationData, getIssueLoader, getIssueIds },
  } = useIssuesStore();

  const [isChangingPage, setIsChangingPage] = useState(false);
  const [pageError, setPageError] = useState(false);
  const pageRequest = useRef<number | null>(null);
  const isRequesting = useRef(false);
  const cancelled = useRef(false);
  useEffect(() => {
    cancelled.current = false;
    return () => {
      cancelled.current = true;
    };
  }, []);
  const clearSelection = selectionHelpers.handleClearSelection;
  useEffect(() => clearSelection(), [clearSelection]);

  const { workflowDisabledSource, isWorkflowDropDisabled, handleWorkFlowState, getIsWorkflowWorkItemCreationDisabled } =
    useWorkFlowFDragNDrop(group_by);
  const isWorkflowIssueCreationDisabled = getIsWorkflowWorkItemCreationDisabled(group.id);

  // The ungrouped store uses the global cursor; group ids must never leak into that request.
  const requestGroupId = group_by ? group.id : undefined;
  const groupIssueCount = getGroupIssueCount(requestGroupId, undefined, false) ?? groupIssueIds.length;
  const isPaginating = !!getIssueLoader(requestGroupId);
  const pageWindow = listPageWindow(groupIssueIds, groupIssueCount, !!group_by, page, pageSize);

  const changePage = useCallback(
    async (requestedPage: number) => {
      if (isRequesting.current || isPaginating) return;
      isRequesting.current = true;
      pageRequest.current = requestedPage;
      setIsChangingPage(true);
      setPageError(false);
      try {
        const window = await loadListPage(
          requestedPage,
          !!group_by,
          () => {
            const ids = getIssueIds(requestGroupId) ?? groupIssueIds;
            const total = getGroupIssueCount(requestGroupId, undefined, false) ?? ids.length;
            const next = getPaginationData(requestGroupId, undefined)?.nextPageResults;
            return { ids, total, hasMore: next === undefined ? ids.length < total : !!next };
          },
          () => {
            if (cancelled.current) throw new Error("分页范围已变更");
            return loadMoreIssues(requestGroupId);
          },
          pageSize
        );
        if (cancelled.current) return;
        selectionHelpers.handleClearSelection();
        onPageChange(window.page);
      } catch {
        if (!cancelled.current) setPageError(true);
      } finally {
        isRequesting.current = false;
        if (!cancelled.current) setIsChangingPage(false);
      }
    },
    [
      isPaginating,
      pageSize,
      group_by,
      getIssueIds,
      requestGroupId,
      groupIssueIds,
      getGroupIssueCount,
      getPaginationData,
      loadMoreIssues,
      selectionHelpers,
      onPageChange,
    ]
  );

  const validateEmptyIssueGroups = (issueCount: number = 0) => {
    if (!showEmptyGroup && issueCount <= 0) return false;
    return true;
  };

  const prePopulateQuickAddData = (groupByKey: string | null, value: any) => {
    const defaultState = projectState.projectStates?.find((state) => state.default);
    let preloadedData: object = { state_id: defaultState?.id };

    if (groupByKey === null || value === "None" || value === "null") {
      preloadedData = { ...preloadedData };
    } else {
      if (groupByKey === "state") {
        preloadedData = { ...preloadedData, state_id: value };
      } else if (groupByKey === "priority") {
        preloadedData = { ...preloadedData, priority: value };
      } else if (groupByKey === "labels" && value != "None") {
        preloadedData = { ...preloadedData, label_ids: [value] };
      } else if (groupByKey === "assignees" && value != "None") {
        preloadedData = { ...preloadedData, assignee_ids: [value] };
      } else if (groupByKey === "cycle" && value != "None") {
        preloadedData = { ...preloadedData, cycle_id: value };
      } else if (groupByKey === "module" && value != "None") {
        preloadedData = { ...preloadedData, module_ids: [value] };
      } else if (groupByKey === "created_by") {
        preloadedData = { ...preloadedData };
      } else {
        preloadedData = { ...preloadedData, [groupByKey]: value };
      }
    }

    return preloadedData;
  };

  useEffect(() => {
    const element = groupRef.current;

    if (!element) return;

    return combine(
      dropTargetForElements({
        element,
        getData: () => ({ groupId: group.id, type: "COLUMN" }),
        onDragEnter: () => {
          setIsDraggingOverColumn(true);
        },
        onDragLeave: () => {
          setIsDraggingOverColumn(false);
        },
        onDragStart: () => {
          setIsDraggingOverColumn(true);
        },
        onDrag: ({ source }) => {
          const sourceGroupId = source?.data?.groupId as string | undefined;
          const currentGroupId = group.id;

          // oxlint-disable-next-line no-unused-expressions
          sourceGroupId && handleWorkFlowState(sourceGroupId, currentGroupId);

          const sourceIndex = getGroupIndex(sourceGroupId);
          const currentIndex = getGroupIndex(currentGroupId);

          if (sourceIndex > currentIndex) {
            setDragColumnOrientation("justify-end");
          } else {
            setDragColumnOrientation("justify-start");
          }
        },
        onDrop: (payload) => {
          setIsDraggingOverColumn(false);
          const source = getSourceFromDropPayload(payload);
          const destination = getDestinationFromDropPayload(payload);

          if (!source || !destination) return;

          if (isWorkflowDropDisabled || group.isDropDisabled) {
            if (group.dropErrorMessage)
              setToast({
                type: TOAST_TYPE.WARNING,
                title: t("common.warning"),
                message: group.dropErrorMessage,
              });
            return;
          }

          handleOnDrop(source, destination);

          highlightIssueOnDrop(getIssueBlockId(source.id, destination?.groupId), orderBy !== "sort_order");

          if (!isExpanded) {
            handleCollapsedGroups(group.id);
          }
        },
      })
    );
  }, [
    // oxlint-disable-next-line eslint-plugin-react-hooks/exhaustive-deps
    groupRef?.current,
    group,
    orderBy,
    getGroupIndex,
    setDragColumnOrientation,
    setIsDraggingOverColumn,
    isWorkflowDropDisabled,
  ]);

  const isDragAllowed = group_by ? DRAG_ALLOWED_GROUPS.includes(group_by) : true;
  const canOverlayBeVisible = isWorkflowDropDisabled || orderBy !== "sort_order" || !!group.isDropDisabled;
  const isDropDisabled = isWorkflowDropDisabled || !!group.isDropDisabled;

  const isGroupByCreatedBy = group_by === "created_by";
  const shouldExpand = (!!groupIssueCount && isExpanded) || !group_by;

  return validateEmptyIssueGroups(groupIssueCount) ? (
    <div
      ref={groupRef}
      data-list-group={group.name}
      data-loaded-count={groupIssueIds.length}
      data-total-count={groupIssueCount}
      data-page={pageWindow.page}
      data-visible-count={pageWindow.visibleIds.length}
      className={cn(`relative flex flex-shrink-0 flex-col`, {
        "border-accent-strong": isDraggingOverColumn,
        "border-danger-subtle": isDraggingOverColumn && isDropDisabled,
      })}
    >
      <Row
        className={cn("w-full flex-shrink-0 border-b border-subtle bg-layer-1 py-1 pr-3 hover:bg-layer-1-hover", {
          "sticky top-0 z-[2]": isExpanded && groupIssueCount > 0,
        })}
      >
        <HeaderGroupByCard
          groupID={group.id}
          groupBy={group_by}
          icon={group.icon}
          title={group.name}
          count={groupIssueCount}
          issuePayload={group.payload}
          canEditProperties={canEditProperties}
          disableIssueCreation={
            disableIssueCreation || isGroupByCreatedBy || isCompletedCycle || isWorkflowIssueCreationDisabled
          }
          addIssuesToView={addIssuesToView}
          selectionHelpers={selectionHelpers}
          handleCollapsedGroups={handleCollapsedGroups}
          isEpic={isEpic}
        />
      </Row>
      {shouldExpand && (
        <div className="relative">
          <GroupDragOverlay
            dragColumnOrientation={dragColumnOrientation}
            canOverlayBeVisible={canOverlayBeVisible}
            isDropDisabled={isDropDisabled}
            workflowDisabledSource={workflowDisabledSource}
            dropErrorMessage={group.dropErrorMessage}
            orderBy={orderBy}
            isDraggingOverColumn={isDraggingOverColumn}
            isEpic={isEpic}
          />
          {groupIssueIds && (
            <IssueBlocksList
              issueIds={pageWindow.visibleIds}
              groupId={group.id}
              issuesMap={issuesMap}
              updateIssue={updateIssue}
              quickActions={quickActions}
              displayProperties={displayProperties}
              canEditProperties={canEditProperties}
              containerRef={containerRef}
              isDragAllowed={isDragAllowed}
              canDropOverIssue={!canOverlayBeVisible}
              selectionHelpers={selectionHelpers}
              isEpic={isEpic}
            />
          )}

          <ListPagination
            label={group.name}
            {...pageWindow}
            total={groupIssueCount}
            onPageSizeChange={onPageSizeChange}
            busy={isChangingPage || isPaginating}
            error={pageError}
            onPage={changePage}
            onRetry={() => changePage(pageRequest.current ?? pageWindow.page)}
          />

          {enableIssueQuickAdd &&
            !disableIssueCreation &&
            !isGroupByCreatedBy &&
            !isCompletedCycle &&
            !isWorkflowIssueCreationDisabled && (
              <div className="sticky bottom-0 z-[1] w-full flex-shrink-0">
                <QuickAddIssueRoot
                  layout={EIssueLayoutTypes.LIST}
                  QuickAddButton={ListQuickAddIssueButton}
                  prePopulatedData={prePopulateQuickAddData(group_by, group.id)}
                  containerClassName="border-b border-t border-subtle bg-surface-1 "
                  quickAddCallback={quickAddCallback}
                  isEpic={isEpic}
                />
              </div>
            )}
        </div>
      )}
    </div>
  ) : null;
});
